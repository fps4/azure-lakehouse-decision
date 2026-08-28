"""Deterministic event and record generation.

No wall clock and no ``random`` — two runs of this repo differ only in timings.
A simulation whose input moves cannot be used to argue about its output, and
arguing about the output is the entire purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A small linear congruential generator. Deterministic, seeded explicitly, and
#: short enough to read — which matters more here than statistical quality.
_A, _C, _M = 1103515245, 12345, 2**31


def lcg(seed: int):
    state = seed % _M

    def nxt() -> float:
        nonlocal state
        state = (_A * state + _C) % _M
        return state / _M

    return nxt


@dataclass(frozen=True)
class Event:
    """One payment event as it reaches the platform.

    ``event_time_s`` is when it happened. ``ingest_time_s`` is when the platform
    saw it. Everything interesting in this repo lives in the gap between them.
    """

    event_id: str
    event_time_s: int
    ingest_time_s: int
    amount_cents: int

    @property
    def lateness_s(self) -> int:
        return self.ingest_time_s - self.event_time_s


def payment_events(
    n: int = 20_000,
    horizon_s: int = 7200,
    late_fraction: float = 0.09,
    max_lateness_s: int = 5400,
    duplicate_fraction: float = 0.02,
    seed: int = 20260828,
) -> list[Event]:
    """Two hours of payment traffic from clients that go offline and come back.

    Two things are deliberately true of this stream, and they are the two things a
    settlement ledger cannot be wrong about:

    * a share of events arrive **late** — a mobile client was in a tunnel, and the
      payment it is reporting happened up to 90 minutes ago; and
    * a share arrive **twice** — an at-least-once delivery path did its job.

    Both are ordinary. Neither is an edge case. An engine that cannot restate a
    window and cannot deduplicate a sink will get a different number from the one
    the business will get when it reconciles, and it will get it silently.
    """
    rnd = lcg(seed)
    events: list[Event] = []
    for i in range(n):
        event_time = int(rnd() * horizon_s)
        if rnd() < late_fraction:
            lateness = int(rnd() * max_lateness_s) + 60
        else:
            lateness = int(rnd() * 20)
        amount = 50 + int(rnd() * 250_00)
        events.append(
            Event(
                event_id=f"pay-{i:07d}",
                event_time_s=event_time,
                ingest_time_s=event_time + lateness,
                amount_cents=amount,
            )
        )

    # Redeliveries: the same event_id, seen again a little later.
    duplicates: list[Event] = []
    for e in events:
        if rnd() < duplicate_fraction:
            duplicates.append(
                Event(
                    event_id=e.event_id,
                    event_time_s=e.event_time_s,
                    ingest_time_s=e.ingest_time_s + 1 + int(rnd() * 30),
                    amount_cents=e.amount_cents,
                )
            )
    events.extend(duplicates)

    # Arrival order is ingestion order. That is the only order a stream actually has.
    events.sort(key=lambda e: (e.ingest_time_s, e.event_id))
    return events


@dataclass(frozen=True)
class OrderRow:
    order_id: int
    customer_id: int
    day: int
    amount_cents: int
    status: str


def order_batch(n: int = 5000, days: int = 14, seed: int = 4711) -> list[OrderRow]:
    """A day-partitioned staging batch for the two load shapes in ``batch.py``."""
    rnd = lcg(seed)
    rows: list[OrderRow] = []
    for i in range(n):
        rows.append(
            OrderRow(
                order_id=i,
                customer_id=int(rnd() * 900) + 1,
                day=int(rnd() * days),
                amount_cents=100 + int(rnd() * 90_000),
                status="settled" if rnd() > 0.12 else "pending",
            )
        )
    return rows
