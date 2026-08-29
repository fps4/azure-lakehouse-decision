"""The economics — and the reason this is not three straight lines.

The three platforms do not merely cost different amounts. Two of them are priced
in one shape and one is priced in another, and the shape is the argument:

* **Databricks and Snowflake are metered.** Near-zero fixed cost, and a straight
  line in consumption. One more workload costs exactly what that workload
  consumes. They differ in *slope*, per surface — Snowflake's warehouse is cheap
  per query-hour and dear per TB scanned, Databricks' jobs compute is cheap for a
  Spark-shaped transformation and Snowpark is not — and that difference is the
  only reason it is worth having both in the comparison at all.
* **Fabric is a pre-paid capacity.** One F-SKU carries the whole estate. One more
  workload costs *nothing* — until the capacity saturates, and then it costs the
  price of the next SKU on the ladder. A step function.

A step function against a straight line has three consequences that a per-workload
comparison cannot show, and they are what this repo exists to make visible:

1. **A workload's platform depends on what else is on the platform.** The same
   workload is free on Fabric with headroom and expensive on Fabric without it.
2. **Unused capacity is a real cost.** An F64 running at 40% is an F64 being paid
   for in full. That is what R8 exists to fix.
3. **The marginal workload that forces a step pays for the whole step**, which is
   why "just add it to Fabric" is sometimes the single most expensive sentence in
   an architecture review.

There is a fourth consequence that only appears once there is more than one
metered platform, and it is the subject of R9: **the fixed cost of operating a
platform is not divisible by workload either.** A meter that wins five workloads
by €200/month each has not won anything if standing it up costs €1,200/month. The
functions here price consumption; that comparison lives in ``rules.py`` because it
can only be made once the whole allocation is known (ADR-0007).

Every euro figure produced here is an illustrative placeholder shaped like list
pricing (ADR-0006). The durable content is the shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import CANDIDATES, Catalog, CostModel, Platform, Workload

#: Seconds in an hour, spelled out because the event-rate conversion is the one
#: place a reader has to trust an arithmetic step.
SECONDS_PER_HOUR = 3600.0


def events_per_month(w: Workload, costs: CostModel) -> float:
    return w.events_per_second * SECONDS_PER_HOUR * costs.hours_per_month


@dataclass(frozen=True)
class Demand:
    """What one workload asks of one platform, before any price is applied.

    Kept separate from cost on purpose. Demand is a property of the workload and
    the platform's engine; price is a property of a contract. Mixing them is how
    a cost model becomes impossible to re-point at a real rate card.
    """

    platform: Platform
    surface: str
    unit_name: str               # CU-h on Fabric, DBU-h on Databricks, credits on Snowflake
    compute_units: float
    from_compute: float
    from_scan: float
    from_events: float
    storage_eur_month: float


def fabric_demand(w: Workload, cat: Catalog) -> Demand:
    """Capacity units per month, plus the storage that is billed outside the capacity."""
    c = cat.costs.fabric
    surface = cat.platforms.fabric.surfaces[w.kind]

    from_compute = w.compute_hours_per_month * c.cu_hours_per_compute_hour.get(surface, 0.0)
    from_scan = w.tb_scanned_per_month * c.cu_hours_per_tb_scanned.get(surface, 0.0)
    from_events = (
        events_per_month(w, cat.costs) / 1e9
    ) * c.cu_hours_per_billion_events.get(surface, 0.0)

    storage = w.size_gb * c.storage_eur_per_gb_month
    if surface == "eventhouse":
        # A KQL database keeps a hot cache sized by retention. It is the line on the
        # invoice that surprises people, so it is modelled rather than folded away.
        storage += w.size_gb * c.eventhouse_hot_cache_eur_per_gb_month

    return Demand(
        platform=Platform.FABRIC,
        surface=surface,
        unit_name="CU-h",
        compute_units=from_compute + from_scan + from_events,
        from_compute=from_compute,
        from_scan=from_scan,
        from_events=from_events,
        storage_eur_month=storage,
    )


def metered_demand(w: Workload, platform: Platform, cat: Catalog) -> Demand:
    """Billing units per month on a metered platform, plus its storage.

    One function for every meter. A DBU-hour and a Snowflake credit are the same
    kind of thing — a unit the platform bills for, driven by compute time, scanned
    volume and event rate — and the only difference between the two platforms is
    the numbers in ``cost_model.yaml``. Writing this twice, once per vendor, is how
    a comparison quietly acquires a favourite.
    """
    c = cat.costs.meter(platform)
    surface = cat.platforms.spec(platform).surfaces[w.kind]

    from_compute = w.compute_hours_per_month * c.units_per_compute_hour.get(surface, 0.0)
    from_scan = w.tb_scanned_per_month * c.units_per_tb_scanned.get(surface, 0.0)
    from_events = (
        events_per_month(w, cat.costs) / 1e9
    ) * c.units_per_billion_events.get(surface, 0.0)

    return Demand(
        platform=platform,
        surface=surface,
        unit_name=c.unit,
        compute_units=from_compute + from_scan + from_events,
        from_compute=from_compute,
        from_scan=from_scan,
        from_events=from_events,
        storage_eur_month=w.size_gb * c.storage_eur_per_gb_month,
    )


def demand(w: Workload, platform: Platform, cat: Catalog) -> Demand:
    if platform is cat.capacity_platform:
        return fabric_demand(w, cat)
    return metered_demand(w, platform, cat)


def metered_run_eur_month(w: Workload, platform: Platform, cat: Catalog) -> float:
    """The metered cost of one workload. Straight-line, and true on its own.

    There is no capacity-platform equivalent of this function, and that absence is
    the point: a Fabric workload has no standalone monthly cost. Asking for one is
    asking the wrong question, and answering it anyway is how capacity platforms get
    mis-compared (ADR-0003, AGENTS.md rule 5).
    """
    d = metered_demand(w, platform, cat)
    rate = cat.costs.meter(platform).eur_per_unit.get(d.surface, 0.0)
    return d.compute_units * rate + d.storage_eur_month


def metered_quotes(w: Workload, cat: Catalog) -> dict[Platform, float]:
    """Every meter's standalone price for this workload, in candidate order.

    A dict rather than a winner, because the caller needs the losers too: the plan
    prints what the rejected option would have cost, and R9 needs the *second*
    cheapest when it asks whether a platform could be closed.
    """
    return {p: metered_run_eur_month(w, p, cat) for p in cat.metered_platforms}


def cheapest_metered(
    w: Workload, cat: Catalog, among: tuple[Platform, ...] | None = None
) -> tuple[Platform, float] | None:
    """The cheapest meter for this workload among those given, or ``None`` if empty.

    Ties break on candidate order, which is fixed, so the plan is deterministic.
    """
    pool = among if among is not None else cat.metered_platforms
    quotes = [(p, metered_run_eur_month(w, p, cat)) for p in pool]
    if not quotes:
        return None
    return min(quotes, key=lambda q: (q[1], CANDIDATES.index(q[0])))


def migration_eur(w: Workload, platform: Platform, cat: Catalog) -> float:
    """One-off cost of moving this workload off Synapse, before amortisation.

    A T-SQL surface the target cannot host is not a harder move, it is a different
    kind of move: the workload is re-expressed rather than migrated. The multiplier
    prices that, and R2 normally eliminates the option before anyone gets to spend
    it — which is the point of having both.
    """
    m = cat.costs.migration
    base = m.eur_per_workload.get(w.kind, 0.0)
    spec = cat.platforms.spec(platform)
    needed = {"procedures": "tsql_procedures", "transactions": "tsql_transactions"}.get(
        w.tsql_surface
    )
    if needed and not getattr(spec.capability, needed):
        return base * m.tsql_rewrite_multiplier
    return base


def migration_eur_month(w: Workload, platform: Platform, cat: Catalog) -> float:
    """The one-off, amortised so it can sit in the same monthly number as run cost.

    Worth stating plainly because the plan makes it obvious and people are usually
    surprised: over a two-year horizon the migration is the larger number, and it
    is *almost the same on every target*. The platform choice moves the smaller
    half of the bill. That does not make the choice unimportant — run cost is the
    half that recurs forever — but an argument about platforms that never says this
    out loud is an argument with a missing premise.
    """
    return migration_eur(w, platform, cat) / cat.costs.migration.amortise_months
