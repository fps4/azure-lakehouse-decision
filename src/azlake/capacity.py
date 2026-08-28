"""Sizing a Fabric capacity — the step function, and why it is planned below its ceiling.

Two things happen here that have no Databricks counterpart.

**The ladder.** Capacity comes in F2, F4, F8 … F2048 and nothing in between. An
estate needing 33 sustained CU buys 64 and pays for 64. The gap between what is
needed and what is bought is not waste to be embarrassed about — it is the price
of the model, and the only question is whether it is being *used*.

**Headroom.** Fabric smooths consumption over time and then throttles when the
smoothed demand runs past the capacity. Planning to 100% of the ceiling therefore
does not mean "fully utilised", it means "throttled at month-end while the
background jobs catch up, with the interactive users noticing first". So the
sizing runs two allowances, and the binding one is reported:

* a whole-estate allowance, against total demand; and
* a stricter interactive allowance, against the demand from workloads that a user
  is sitting in front of.

The second is the one that catches an estate whose *average* looks comfortable and
whose *peak* is a Power BI report at 09:00 on the first working day of the month.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Catalog, Workload
from .econ import fabric_demand

#: Workloads a person is waiting on. They feel a throttle first, so they are sized
#: against the stricter allowance.
INTERACTIVE_CLASSES = frozenset({"interactive", "subsecond"})


@dataclass(frozen=True)
class CapacityPlan:
    """A sized Fabric capacity, and the reason it is that size."""

    sku: int | None
    total_cu_hours: float
    sustained_cu: float
    interactive_cu: float
    required_cu: float
    binding: str
    monthly_eur: float
    storage_eur: float
    workload_ids: list[str] = field(default_factory=list)

    @property
    def utilisation(self) -> float:
        """Sustained demand as a share of what is being paid for."""
        if not self.sku:
            return 0.0
        return self.sustained_cu / self.sku

    @property
    def headroom_cu(self) -> float:
        return (self.sku - self.sustained_cu) if self.sku else 0.0

    @property
    def total_eur(self) -> float:
        return self.monthly_eur + self.storage_eur


def _smallest_sku(required_cu: float, skus: list[int]) -> int | None:
    """The first rung of the ladder that clears the requirement.

    ``None`` when the estate needs more than the largest SKU — a real answer, not an
    error: it means the estate needs more than one capacity, which is a different
    architecture and a different conversation.
    """
    for sku in sorted(skus):
        if sku >= required_cu:
            return sku
    return None


def size_capacity(workloads: list[Workload], cat: Catalog) -> CapacityPlan:
    """Size the capacity that would carry exactly these workloads."""
    pol = cat.policy.capacity
    c = cat.costs.fabric
    hours = cat.costs.hours_per_month

    if not workloads:
        return CapacityPlan(
            sku=None,
            total_cu_hours=0.0,
            sustained_cu=0.0,
            interactive_cu=0.0,
            required_cu=0.0,
            binding="empty",
            monthly_eur=0.0,
            storage_eur=0.0,
            workload_ids=[],
        )

    demands = {w.id: fabric_demand(w, cat) for w in workloads}
    total_cu_hours = sum(d.compute_units for d in demands.values())
    interactive_cu_hours = sum(
        demands[w.id].compute_units for w in workloads if w.latency_class in INTERACTIVE_CLASSES
    )

    sustained = total_cu_hours / hours
    interactive = interactive_cu_hours / hours

    by_total = sustained / pol.headroom
    by_interactive = interactive / pol.interactive_headroom
    required = max(by_total, by_interactive)
    binding = "interactive" if by_interactive > by_total else "total"

    sku = _smallest_sku(required, c.skus)
    monthly = (sku or 0) * c.effective_eur_per_cu_hour * hours
    storage = sum(d.storage_eur_month for d in demands.values())

    return CapacityPlan(
        sku=sku,
        total_cu_hours=total_cu_hours,
        sustained_cu=sustained,
        interactive_cu=interactive,
        required_cu=required,
        binding=binding,
        monthly_eur=monthly,
        storage_eur=storage,
        workload_ids=[w.id for w in workloads],
    )


def marginal_eur(base: CapacityPlan, candidate: CapacityPlan) -> float:
    """What adding a workload to a Fabric capacity actually costs.

    Zero while the capacity absorbs it. The full price of the next rung when it
    does not. This function is the whole reason a per-workload cost table cannot
    answer the platform question on its own.
    """
    return candidate.monthly_eur - base.monthly_eur
