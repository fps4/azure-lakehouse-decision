"""R2, executed: what a transactional T-SQL surface is actually buying.

R2 eliminates a platform that cannot host a workload's T-SQL surface, and that
elimination is easy to read as pedantry — SQL is SQL, and a MERGE is a MERGE.
It is not pedantry, and this is the difference, run rather than argued.

Both shapes load the same staging batch into the same fact and maintain the same
customer aggregate. Then the load is killed halfway through, which is what
actually happens at 03:00.

**Warehouse-shaped** keeps the fact and the aggregate consistent by writing them
in **one multi-table transaction**. Killed halfway, it rolls back to the state it
started in and the retry is clean. Take the transaction away — which is what
porting it to a platform without multi-table transactions does — and the same
failure leaves the aggregate disagreeing with the fact it was derived from, with
nothing in either table saying so.

**Lakehouse-shaped** never needs the transaction, because it never maintains the
aggregate incrementally. It **replaces whole day partitions** and recomputes the
aggregate from the fact. Killed halfway, the retry converges on the same answer.

Both are correct designs. They are not the same design, and the second is not a
port of the first — it is a rewrite of how consistency is achieved. That is the
sentence R2 exists to keep in the room.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from .generate import OrderRow, order_batch


class InjectedFailure(RuntimeError):
    """The 03:00 failure, on purpose and at a chosen line."""


@dataclass(frozen=True)
class BatchResult:
    rows_loaded: int
    warehouse_consistent_with_transaction: bool
    warehouse_consistent_without_transaction: bool
    lakehouse_consistent_after_retry: bool
    parity: bool
    torn_customers: int
    warehouse_total_cents: int
    lakehouse_total_cents: int


def _schema(con: duckdb.DuckDBPyConnection, prefix: str) -> None:
    con.execute(
        f"CREATE OR REPLACE TABLE {prefix}_fact ("
        "  order_id BIGINT, customer_id BIGINT, day BIGINT,"
        "  amount_cents BIGINT, status VARCHAR)"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE {prefix}_agg (customer_id BIGINT, settled_cents BIGINT)"
    )


def _stage(con: duckdb.DuckDBPyConnection, rows: list[OrderRow]) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE staging ("
        "  order_id BIGINT, customer_id BIGINT, day BIGINT,"
        "  amount_cents BIGINT, status VARCHAR)"
    )
    con.executemany(
        "INSERT INTO staging VALUES (?, ?, ?, ?, ?)",
        [(r.order_id, r.customer_id, r.day, r.amount_cents, r.status) for r in rows],
    )


def _torn(con: duckdb.DuckDBPyConnection, prefix: str) -> int:
    """Customers whose stored aggregate disagrees with the fact beneath it."""
    return con.execute(
        f"""
        WITH derived AS (
          SELECT customer_id, SUM(amount_cents) AS cents
          FROM {prefix}_fact WHERE status = 'settled' GROUP BY 1
        )
        SELECT COUNT(*) FROM (
          SELECT COALESCE(a.customer_id, d.customer_id) AS c,
                 COALESCE(a.settled_cents, 0) AS stored,
                 COALESCE(d.cents, 0)         AS actual
          FROM {prefix}_agg a FULL OUTER JOIN derived d USING (customer_id)
        ) WHERE stored <> actual
        """
    ).fetchone()[0]


def _warehouse_load(
    con: duckdb.DuckDBPyConnection, *, transactional: bool, fail_after_insert: bool
) -> None:
    """Insert the fact and maintain the aggregate — the two-statement write."""
    if transactional:
        con.execute("BEGIN TRANSACTION")
    try:
        con.execute("INSERT INTO wh_fact SELECT * FROM staging")
        if fail_after_insert:
            raise InjectedFailure("killed between the fact write and the aggregate write")
        con.execute("DELETE FROM wh_agg")
        con.execute(
            "INSERT INTO wh_agg SELECT customer_id, SUM(amount_cents) "
            "FROM wh_fact WHERE status = 'settled' GROUP BY 1"
        )
        if transactional:
            con.execute("COMMIT")
    except InjectedFailure:
        if transactional:
            con.execute("ROLLBACK")
        raise


def _lakehouse_load(
    con: duckdb.DuckDBPyConnection, days: list[int], *, fail_after_day: int | None
) -> None:
    """Replace whole day partitions, then recompute the aggregate from the fact.

    No transaction spans the two, because nothing here has to be atomic across
    them: replacing a partition is idempotent, and the aggregate is derived rather
    than maintained.
    """
    for day in days:
        con.execute("DELETE FROM lh_fact WHERE day = ?", [day])
        con.execute("INSERT INTO lh_fact SELECT * FROM staging WHERE day = ?", [day])
        if fail_after_day is not None and day == fail_after_day:
            raise InjectedFailure(f"killed after replacing partition day={day}")
    con.execute("DELETE FROM lh_agg")
    con.execute(
        "INSERT INTO lh_agg SELECT customer_id, SUM(amount_cents) "
        "FROM lh_fact WHERE status = 'settled' GROUP BY 1"
    )


def run_batch(rows: list[OrderRow] | None = None) -> BatchResult:
    rows = rows if rows is not None else order_batch()
    con = duckdb.connect()
    _stage(con, rows)
    days = [r[0] for r in con.execute("SELECT DISTINCT day FROM staging ORDER BY 1").fetchall()]

    # ---- warehouse, with the transaction -------------------------------------
    _schema(con, "wh")
    try:
        _warehouse_load(con, transactional=True, fail_after_insert=True)
    except InjectedFailure:
        pass
    rolled_back_clean = _torn(con, "wh") == 0
    _warehouse_load(con, transactional=True, fail_after_insert=False)
    with_transaction_ok = _torn(con, "wh") == 0 and rolled_back_clean
    wh_total = con.execute("SELECT COALESCE(SUM(settled_cents), 0) FROM wh_agg").fetchone()[0]

    # ---- the same load, ported to a platform without multi-table transactions -
    _schema(con, "wh")
    try:
        _warehouse_load(con, transactional=False, fail_after_insert=True)
    except InjectedFailure:
        pass
    torn = _torn(con, "wh")
    without_transaction_ok = torn == 0

    # ---- lakehouse, killed mid-load and simply re-run -------------------------
    _schema(con, "lh")
    try:
        _lakehouse_load(con, days, fail_after_day=days[len(days) // 2])
    except InjectedFailure:
        pass
    _lakehouse_load(con, days, fail_after_day=None)
    lakehouse_ok = _torn(con, "lh") == 0
    lh_total = con.execute("SELECT COALESCE(SUM(settled_cents), 0) FROM lh_agg").fetchone()[0]

    # ---- and, having survived differently, do they agree? ---------------------
    _schema(con, "wh")
    _warehouse_load(con, transactional=True, fail_after_insert=False)
    wh_total = con.execute("SELECT COALESCE(SUM(settled_cents), 0) FROM wh_agg").fetchone()[0]
    parity = (
        con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT * FROM wh_fact EXCEPT SELECT * FROM lh_fact"
            "  UNION ALL"
            "  SELECT * FROM lh_fact EXCEPT SELECT * FROM wh_fact)"
        ).fetchone()[0]
        == 0
        and wh_total == lh_total
    )

    result = BatchResult(
        rows_loaded=len(rows),
        warehouse_consistent_with_transaction=with_transaction_ok,
        warehouse_consistent_without_transaction=without_transaction_ok,
        lakehouse_consistent_after_retry=lakehouse_ok,
        parity=parity,
        torn_customers=torn,
        warehouse_total_cents=wh_total,
        lakehouse_total_cents=lh_total,
    )
    con.close()
    return result
