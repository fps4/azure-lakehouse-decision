"""The economics — and the reason this is not two straight lines.

The two platforms do not merely cost different amounts. They are priced in
different *shapes*, and the shape is the argument:

* **Databricks is metered.** Near-zero fixed cost, and a straight line in
  consumption. One more workload costs exactly what that workload consumes.
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

Every euro figure produced here is an illustrative placeholder shaped like list
pricing (ADR-0006). The durable content is the shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog, CostModel, Platform, Workload

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
    compute_units: float          # CU-hours on Fabric, DBU-hours on Databricks
    from_compute: float
    from_scan: float
    from_events: float
    storage_eur_month: float

    @property
    def unit_name(self) -> str:
        return "CU-h" if self.platform is Platform.FABRIC else "DBU-h"


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
        compute_units=from_compute + from_scan + from_events,
        from_compute=from_compute,
        from_scan=from_scan,
        from_events=from_events,
        storage_eur_month=storage,
    )


def databricks_demand(w: Workload, cat: Catalog) -> Demand:
    """DBU-hours per month, plus ADLS storage."""
    c = cat.costs.databricks
    surface = cat.platforms.databricks.surfaces[w.kind]

    from_compute = w.compute_hours_per_month * c.dbu_hours_per_compute_hour.get(surface, 0.0)
    from_scan = w.tb_scanned_per_month * c.dbu_hours_per_tb_scanned.get(surface, 0.0)
    from_events = (
        events_per_month(w, cat.costs) / 1e9
    ) * c.dbu_hours_per_billion_events.get(surface, 0.0)

    return Demand(
        platform=Platform.DATABRICKS,
        surface=surface,
        compute_units=from_compute + from_scan + from_events,
        from_compute=from_compute,
        from_scan=from_scan,
        from_events=from_events,
        storage_eur_month=w.size_gb * c.storage_eur_per_gb_month,
    )


def demand(w: Workload, platform: Platform, cat: Catalog) -> Demand:
    if platform is Platform.FABRIC:
        return fabric_demand(w, cat)
    return databricks_demand(w, cat)


def databricks_run_eur_month(w: Workload, cat: Catalog) -> float:
    """The metered cost of one workload. Straight-line, and true on its own.

    There is no Fabric equivalent of this function, and that absence is the point:
    a Fabric workload has no standalone monthly cost. Asking for one is asking the
    wrong question, and answering it anyway is how capacity platforms get
    mis-compared.
    """
    d = databricks_demand(w, cat)
    rate = cat.costs.databricks.eur_per_dbu.get(d.surface, 0.0)
    return d.compute_units * rate + d.storage_eur_month


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
    is *almost the same for both platforms*. The platform choice moves the smaller
    half of the bill. That does not make the choice unimportant — run cost is the
    half that recurs forever — but an argument about platforms that never says this
    out loud is an argument with a missing premise.
    """
    return migration_eur(w, platform, cat) / cat.costs.migration.amortise_months
