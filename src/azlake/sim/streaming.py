"""R3, executed: an ingestion-time engine is not a cheaper event-time engine.

The same events, from the same Event Hub, down two shapes.

**Eventhouse-shaped** — append on arrival, aggregate by *ingestion time*, never go
back. This is what a KQL database is built for and it is genuinely excellent at
it: append-only telemetry where "when did we see it" is the question. Every event
is counted, in the minute it arrived.

**Structured-Streaming-shaped** — micro-batch, aggregate by *event time* behind a
watermark, and MERGE the result into a keyed sink. A late event lands in the
window it belongs to and the window is **restated**. A redelivered event is
recognised and **not counted twice**.

For a settlement ledger the second shape is not a nicer version of the first. It
is the only one that agrees with the business, and the number below is how far
apart they finish.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .generate import Event, payment_events

#: One minute windows, and a watermark generous enough to admit the estate's stated
#: 120-minute late-arrival tolerance. Both come from the same place a real design
#: would take them: the workload's contract, not the engine's default.
WINDOW_S = 600
WATERMARK_S = 7200
MICRO_BATCH_S = 300


@dataclass(frozen=True)
class StreamResult:
    windows: int
    truth_total_cents: int
    eventhouse_total_cents: int
    streaming_total_cents: int
    eventhouse_misplaced_cents: int
    eventhouse_window_error_cents: int
    streaming_window_error_cents: int
    duplicates_counted_by_eventhouse: int
    late_events: int
    restatements: int

    @property
    def eventhouse_error_pct(self) -> float:
        return 100.0 * self.eventhouse_window_error_cents / max(self.truth_total_cents, 1)

    @property
    def streaming_error_pct(self) -> float:
        return 100.0 * self.streaming_window_error_cents / max(self.truth_total_cents, 1)


def _load(con: duckdb.DuckDBPyConnection, events: list[Event]) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE arrivals ("
        "  seq BIGINT, event_id VARCHAR, event_time_s BIGINT,"
        "  ingest_time_s BIGINT, amount_cents BIGINT)"
    )
    con.executemany(
        "INSERT INTO arrivals VALUES (?, ?, ?, ?, ?)",
        [
            (i, e.event_id, e.event_time_s, e.ingest_time_s, e.amount_cents)
            for i, e in enumerate(events)
        ],
    )


def run_streaming(events: list[Event] | None = None) -> tuple[StreamResult, list[dict]]:
    events = events if events is not None else payment_events()
    con = duckdb.connect()
    _load(con, events)

    # ---- ground truth --------------------------------------------------------
    # What the business will get when it reconciles: every *distinct* payment,
    # counted in the window it actually happened in.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE truth AS
        SELECT (event_time_s / {WINDOW_S})::BIGINT AS w,
               SUM(amount_cents)::BIGINT           AS cents
        FROM (SELECT DISTINCT event_id, event_time_s, amount_cents FROM arrivals)
        GROUP BY 1
        """
    )

    # ---- the Eventhouse shape ------------------------------------------------
    # Append on arrival; bucket by ingestion time; every delivery is a row. Nothing
    # here is a bug — it is the engine behaving exactly as designed, on a workload
    # that needed a different design.
    con.execute(
        f"""
        CREATE OR REPLACE TABLE eventhouse AS
        SELECT (ingest_time_s / {WINDOW_S})::BIGINT AS w,
               SUM(amount_cents)::BIGINT            AS cents
        FROM arrivals
        GROUP BY 1
        """
    )

    # ---- the Structured Streaming shape --------------------------------------
    # Micro-batches in ingestion order. Within each batch: drop anything already
    # seen (the exactly-once sink), bucket by *event* time, and MERGE into the
    # keyed sink so a late arrival restates the window it belongs to rather than
    # landing in the window it arrived in.
    con.execute("CREATE OR REPLACE TABLE seen (event_id VARCHAR PRIMARY KEY)")
    con.execute("CREATE OR REPLACE TABLE sink (w BIGINT PRIMARY KEY, cents BIGINT)")

    max_ingest = con.execute("SELECT MAX(ingest_time_s) FROM arrivals").fetchone()[0]
    restatements = 0
    batch_start = 0
    while batch_start <= max_ingest:
        batch_end = batch_start + MICRO_BATCH_S
        watermark = batch_end - WATERMARK_S

        con.execute(
            """
            CREATE OR REPLACE TEMP TABLE batch AS
            SELECT a.event_id, a.event_time_s, a.amount_cents
            FROM arrivals a
            WHERE a.ingest_time_s >= ? AND a.ingest_time_s < ?
              AND NOT EXISTS (SELECT 1 FROM seen s WHERE s.event_id = a.event_id)
            QUALIFY ROW_NUMBER() OVER (PARTITION BY a.event_id ORDER BY a.event_time_s) = 1
            """,
            [batch_start, batch_end],
        )
        con.execute("INSERT INTO seen SELECT DISTINCT event_id FROM batch")

        # Events older than the watermark are dropped rather than silently
        # mis-placed. Dropping late data is a decision; hiding it is not.
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE agg AS
            SELECT (event_time_s / {WINDOW_S})::BIGINT AS w,
                   SUM(amount_cents)::BIGINT           AS cents
            FROM batch
            WHERE event_time_s >= ?
            GROUP BY 1
            """,
            [watermark],
        )
        restatements += con.execute(
            "SELECT COUNT(*) FROM agg JOIN sink USING (w)"
        ).fetchone()[0]

        # The MERGE. This is the exactly-once sink, and it is why the second shape
        # can be re-run without double counting.
        con.execute(
            """
            INSERT INTO sink SELECT w, cents FROM agg
            ON CONFLICT (w) DO UPDATE SET cents = sink.cents + excluded.cents
            """
        )
        batch_start = batch_end

    comparison = con.execute(
        """
        SELECT t.w                                   AS w,
               t.cents                               AS truth,
               COALESCE(e.cents, 0)                  AS eventhouse,
               COALESCE(s.cents, 0)                  AS streaming
        FROM truth t
        LEFT JOIN eventhouse e USING (w)
        LEFT JOIN sink s USING (w)
        ORDER BY t.w
        """
    ).fetchall()

    truth_total = con.execute("SELECT SUM(cents) FROM truth").fetchone()[0]
    eh_total = con.execute("SELECT SUM(cents) FROM eventhouse").fetchone()[0]
    st_total = con.execute("SELECT SUM(cents) FROM sink").fetchone()[0]

    eh_window_error = sum(abs(r[2] - r[1]) for r in comparison)
    st_window_error = sum(abs(r[3] - r[1]) for r in comparison)

    misplaced = con.execute(
        f"""
        SELECT COALESCE(SUM(amount_cents), 0) FROM (
          SELECT DISTINCT event_id, event_time_s, ingest_time_s, amount_cents FROM arrivals
        )
        WHERE (event_time_s / {WINDOW_S})::BIGINT <> (ingest_time_s / {WINDOW_S})::BIGINT
        """
    ).fetchone()[0]
    dupes = con.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT event_id) FROM arrivals"
    ).fetchone()[0]
    late = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT event_id, ingest_time_s - event_time_s AS l "
        "FROM arrivals) WHERE l > 60"
    ).fetchone()[0]

    result = StreamResult(
        windows=len(comparison),
        truth_total_cents=truth_total,
        eventhouse_total_cents=eh_total,
        streaming_total_cents=st_total,
        eventhouse_misplaced_cents=misplaced,
        eventhouse_window_error_cents=eh_window_error,
        streaming_window_error_cents=st_window_error,
        duplicates_counted_by_eventhouse=dupes,
        late_events=late,
        restatements=restatements,
    )
    rows = [
        {"window": r[0], "truth": r[1], "eventhouse": r[2], "streaming": r[3]}
        for r in comparison
    ]
    con.close()
    return result, rows
