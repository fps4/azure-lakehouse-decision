"""The decision rules — ordered, named, and each one able to say why.

The order is the argument:

    R1  residency & clearance        constraints, not preferences
    R2  T-SQL surface                can the target host what the source is written in?
    R3  streaming semantics          event-time restatement and exactly-once
    R4  sub-second telemetry         the mirror constraint, pointing the other way
    R5  ML lifecycle                 tracking, registry, a served endpoint
    R6  semantics premium            Direct Lake is worth a bounded amount
    R7  economics, capacity-aware    only now, and only among survivors
    R8  step-boundary review         is the capacity we bought the one we should own?
    R9  locality                     advisory: shortcut, do not copy

Rules R1–R5 *eliminate*. Rule R7 *chooses*. That separation is the whole point:
a residency rule is not a number you can trade against a cheaper option, and a
design that lets economics overrule it is a design that will one day be overruled
by an auditor instead (ADR-0002).

R7 is where this differs from a per-workload comparison, and the difference is
structural rather than cosmetic. Fabric has no per-workload price — it has a
capacity, and a workload's cost on it is whatever it does to the size of that
capacity. So R7 cannot score workloads independently and sort them. It has to
place them one at a time against a capacity that changes underneath it, which is
why the code below reads as an allocation and not as a table (ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .capacity import CapacityPlan, size_capacity
from .catalog import (
    CANDIDATES,
    TSQL_SURFACES_NEEDING_SUPPORT,
    Catalog,
    Platform,
    Workload,
)
from .econ import databricks_run_eur_month, fabric_demand, migration_eur_month


@dataclass
class Placement:
    """One workload's outcome, with the reasoning kept attached to it."""

    workload_id: str
    name: str
    domain: str
    kind: str
    platform: Platform
    surface: str
    rule_id: str
    reason: str
    eliminated: dict[Platform, str] = field(default_factory=dict)
    databricks_eur_month: float = 0.0
    fabric_cu_hours: float = 0.0
    marginal_eur: float = 0.0
    migration_eur_month: float = 0.0
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def run_eur_month(self) -> float:
        """What this workload adds to the monthly run bill, on the platform chosen.

        On Databricks that is its metered cost. On Fabric it is its *marginal*
        cost — zero when the capacity absorbed it, the price of a rung when it did
        not. A Fabric workload showing €0 is not free: it is riding capacity the
        estate already pays for, and `reports/plan.md` totals the capacity
        separately so that nobody reads the zero as an absence.
        """
        if self.platform is Platform.DATABRICKS:
            return self.databricks_eur_month
        if self.platform is Platform.FABRIC:
            return self.marginal_eur
        return 0.0


@dataclass
class StepReview:
    """R8 — whether the capacity that came out of R7 is the one to own."""

    considered_sku: int | None
    evicted: list[str]
    saving_eur: float
    added_databricks_eur: float
    net_eur: float
    applied: bool
    reason: str


@dataclass
class Plan:
    placements: list[Placement]
    capacity: CapacityPlan
    step_review: StepReview
    catalog: Catalog

    def by_platform(self, platform: Platform) -> list[Placement]:
        return [p for p in self.placements if p.platform is platform]

    @property
    def platform_overhead_eur(self) -> float:
        """Two platforms means two of these. It is the number "just use both" forgets."""
        oh = self.catalog.costs.platform_overhead_eur_per_month
        total = 0.0
        if self.by_platform(Platform.FABRIC):
            total += oh.get("fabric", 0.0)
        if self.by_platform(Platform.DATABRICKS):
            total += oh.get("databricks", 0.0)
        return total

    @property
    def databricks_run_eur(self) -> float:
        return sum(p.databricks_eur_month for p in self.by_platform(Platform.DATABRICKS))

    @property
    def run_eur_month(self) -> float:
        return (
            self.capacity.total_eur
            + self.databricks_run_eur
            + self.platform_overhead_eur
        )

    @property
    def migration_eur_month(self) -> float:
        return sum(p.migration_eur_month for p in self.placements)

    @property
    def total_eur_month(self) -> float:
        return self.run_eur_month + self.migration_eur_month


# ---------------------------------------------------------------------------
# R1–R5 · elimination
# ---------------------------------------------------------------------------


def assess(w: Workload, cat: Catalog) -> tuple[dict[Platform, str], list[str], list[str]]:
    """Which platforms are ruled out for this workload, and why.

    Deliberately one linear function. Its ordering *is* the design, and splitting
    it into per-rule helpers would satisfy a linter while hiding the argument.
    """
    eliminated: dict[Platform, str] = {}
    notes: list[str] = []
    flags: list[str] = []
    pol = cat.policy

    for platform in CANDIDATES:
        spec = cat.platforms.spec(platform)

        # ---- R1 · residency and clearance -----------------------------------
        if pol.residency.enforce:
            if not set(w.governance.residency) & set(spec.regions):
                allowed = ", ".join(w.governance.residency)
                eliminated[platform] = (
                    f"[R1] data may only come to rest in [{allowed}]; {spec.name} has no "
                    f"home there"
                )
                continue
            if (
                pol.residency.restricted_requires_cleared_platform
                and w.governance.classification == "restricted"
                and platform.value.lower() != pol.residency.cleared_platform_for_restricted
            ):
                eliminated[platform] = (
                    f"[R1] restricted classification: the estate has cleared "
                    f"{pol.residency.cleared_platform_for_restricted} for this data and not "
                    f"{spec.name}. Clearing a second platform is a governance project, not "
                    f"a configuration change"
                )
                flags.append("restricted")
                continue

        # ---- R2 · the T-SQL surface -----------------------------------------
        needed = TSQL_SURFACES_NEEDING_SUPPORT.get(w.tsql_surface)
        if needed and pol.tsql.eliminate_when_surface_unsupported:
            if not getattr(spec.capability, needed):
                eliminated[platform] = (
                    f"[R2] the workload is written as T-SQL {w.tsql_surface}; {spec.name} "
                    f"does not host that surface, so this is a rewrite rather than a "
                    f"migration — priced in the cost model, and deliberately not "
                    f"purchasable here"
                )
                flags.append("tsql-locked")
                continue

        # ---- R3 · streaming semantics ---------------------------------------
        if w.kind == "stream" and pol.streaming.eliminate_when_semantics_unsupported:
            if w.needs_event_time_restatement and not spec.capability.event_time_restatement:
                eliminated[platform] = (
                    f"[R3] events arrive up to {w.late_arrival_tolerance_minutes:.0f} min "
                    f"late and the window has to be restated by event time; {spec.name} "
                    f"aggregates by ingestion time and does not go back"
                )
                flags.append("event-time")
                continue
            if w.exactly_once_required and not spec.capability.exactly_once_streaming:
                eliminated[platform] = (
                    f"[R3] the sink must be exactly-once; {spec.name} does not offer that "
                    f"guarantee, and for a ledger 'nearly once' is a different product"
                )
                flags.append("exactly-once")
                continue

        # ---- R4 · sub-second telemetry --------------------------------------
        if (
            w.needs_subsecond
            and pol.streaming.subsecond_requires_capable_platform
            and not spec.capability.subsecond_telemetry
        ):
            eliminated[platform] = (
                f"[R4] sub-second interactive query over high-cardinality telemetry at "
                f"{w.peak_concurrency} concurrent; {spec.name} can be made to do it with "
                f"enough warm compute, which is a way of saying it is the wrong engine"
            )
            flags.append("subsecond")
            continue

        # ---- R5 · ML lifecycle ----------------------------------------------
        if (
            w.ml_lifecycle
            and pol.ml.eliminate_when_lifecycle_unsupported
            and not spec.capability.ml_lifecycle
        ):
            eliminated[platform] = (
                f"[R5] experiment tracking, a model registry and a served endpoint; "
                f"{spec.name} has the pieces but not the lifecycle this estate needs"
            )
            flags.append("ml")
            continue

    # ---- R9 · advisory, and only advisory ---------------------------------------
    survivors = [p for p in CANDIDATES if p not in eliminated]
    if len(survivors) == 2 and w.size_gb > 0:
        notes.append(
            "Eligible for both. If it lands away from the rest of its domain, shortcut "
            "the storage rather than copying it — a second physical copy is the cost "
            "that never appears in either platform's bill."
        )
    return eliminated, notes, flags


# ---------------------------------------------------------------------------
# R6–R8 · placement, against a capacity that moves
# ---------------------------------------------------------------------------


def _fabric_pref(w: Workload, cat: Catalog) -> bool:
    """R6 — does this workload buy something on Fabric that Databricks cannot sell?"""
    return (
        cat.policy.semantics.prefer_direct_lake_consumers
        and w.consumer == "powerbi_direct_lake"
        and cat.platforms.fabric.capability.powerbi_direct_lake
    )


def _step_review(
    fabric: list[Workload],
    evictable: list[Workload],
    plan: CapacityPlan,
    cat: Catalog,
) -> tuple[StepReview, list[Workload]]:
    """R8 — the capacity we sized is on a ladder. Is the rung below cheaper to own?

    R7 fills a capacity greedily and stops. That is the right local move and it can
    still leave the estate one rung too high: a handful of batch workloads pushed
    the requirement past a boundary, and their metered cost on Databricks is less
    than the rung they bought. This checks, and prints the answer either way —
    including when the answer is "you cannot get there from here", which is the
    more common one and the more useful.
    """
    skus = sorted(cat.costs.fabric.skus)
    if plan.sku is None or plan.sku == skus[0]:
        return (
            StepReview(None, [], 0.0, 0.0, 0.0, False, "already on the lowest rung"),
            fabric,
        )
    lower = skus[skus.index(plan.sku) - 1]

    # Interactive demand cannot be evicted below its own allowance, and most of it is
    # usually pinned by R1–R5 anyway. Saying so is more useful than a failed search.
    forced = [w for w in fabric if w not in evictable]
    forced_plan = size_capacity(forced, cat)
    if forced_plan.required_cu > lower:
        return (
            StepReview(
                lower,
                [],
                0.0,
                0.0,
                0.0,
                False,
                (
                    f"F{lower} is unreachable: the workloads pinned to Fabric by R1–R5 alone "
                    f"require {forced_plan.required_cu:.1f} CU "
                    f"({forced_plan.binding}-bound). The capacity floor is set by constraints, "
                    f"not by the batch workloads R7 added — so evicting batch cannot shrink it"
                ),
            ),
            fabric,
        )

    # Evict in order of cheapest metered cost per capacity unit freed: the best
    # exchange rate first. Direct Lake consumers go last and have to clear a higher
    # bar, which is R6 doing its work in the only place it can.
    def rate(w: Workload) -> tuple[int, float]:
        cu = fabric_demand(w, cat).compute_units or 1e-9
        return (1 if _fabric_pref(w, cat) else 0, databricks_run_eur_month(w, cat) / cu)

    remaining = list(fabric)
    evicted: list[Workload] = []
    for w in sorted(evictable, key=rate):
        if size_capacity(remaining, cat).required_cu <= lower:
            break
        remaining = [x for x in remaining if x.id != w.id]
        evicted.append(w)

    after = size_capacity(remaining, cat)
    if after.required_cu > lower or not evicted:
        return (
            StepReview(lower, [], 0.0, 0.0, 0.0, False, f"F{lower} not reachable by eviction"),
            fabric,
        )

    saving = plan.monthly_eur - after.monthly_eur
    added = sum(databricks_run_eur_month(w, cat) for w in evicted)
    bar = saving
    if any(_fabric_pref(w, cat) for w in evicted):
        # A Direct Lake workload leaving Fabric gives up something real, so the step
        # down has to be worth more than the arithmetic.
        bar = saving / cat.policy.semantics.max_premium_ratio
    net = saving - added
    applied = bar > added

    if applied:
        reason = (
            f"Stepping F{plan.sku} → F{lower} saves €{saving:,.0f}/month and moves "
            f"{len(evicted)} batch workload(s) onto metered compute for €{added:,.0f}/month. "
            f"Net €{net:,.0f}/month"
        )
        return StepReview(lower, [w.id for w in evicted], saving, added, net, True, reason), remaining

    reason = (
        f"F{lower} is reachable but not worth it: it would save €{saving:,.0f}/month and "
        f"cost €{added:,.0f}/month in metered compute. The capacity is priced correctly at "
        f"F{plan.sku}"
    )
    return StepReview(lower, [w.id for w in evicted], saving, added, net, False, reason), fabric


def build_plan(cat: Catalog) -> Plan:
    """Assess every workload, then place them against a capacity that changes."""
    assessments = {w.id: assess(w, cat) for w in cat.workloads}

    stranded: list[Workload] = []
    forced_fabric: list[Workload] = []
    forced_databricks: list[Workload] = []
    free: list[Workload] = []

    for w in cat.workloads:
        eliminated, _, _ = assessments[w.id]
        survivors = [p for p in CANDIDATES if p not in eliminated]
        if not survivors:
            stranded.append(w)
        elif survivors == [Platform.FABRIC]:
            forced_fabric.append(w)
        elif survivors == [Platform.DATABRICKS]:
            forced_databricks.append(w)
        else:
            free.append(w)

    # ---- R7 · economics, one workload at a time, against a moving capacity -----
    fabric: list[Workload] = list(forced_fabric)
    databricks: list[Workload] = list(forced_databricks)
    current = size_capacity(fabric, cat)
    marginal: dict[str, float] = {w.id: 0.0 for w in forced_fabric}
    r7_reason: dict[str, str] = {}

    # Biggest metered bill first: the workload with most to save is the one that
    # should get first claim on free headroom.
    for w in sorted(free, key=lambda x: -databricks_run_eur_month(x, cat)):
        db = databricks_run_eur_month(w, cat)
        candidate = size_capacity(fabric + [w], cat)
        step = candidate.monthly_eur - current.monthly_eur

        bar = db * cat.policy.semantics.max_premium_ratio if _fabric_pref(w, cat) else db
        if step <= bar:
            fabric.append(w)
            marginal[w.id] = step
            current = candidate
            if step == 0.0:
                r7_reason[w.id] = (
                    f"Absorbed by the F{current.sku} capacity already paid for — marginal "
                    f"cost €0 against €{db:,.0f}/month metered. Free headroom is the "
                    f"cheapest compute in the estate, and the only way to use it is to "
                    f"put something on it"
                )
            else:
                r7_reason[w.id] = (
                    f"Forces F{current.sku} at €{step:,.0f}/month, still under the "
                    f"€{bar:,.0f}/month bar"
                )
        else:
            databricks.append(w)
            r7_reason[w.id] = (
                f"Would push the capacity to F{candidate.sku}, a step of €{step:,.0f}/month, "
                f"against €{db:,.0f}/month metered. The marginal workload that forces a rung "
                f"pays for the whole rung"
            )

    # ---- R8 · is the rung we landed on the one to own? ------------------------
    evictable = [w for w in fabric if w in free]
    review, fabric = _step_review(fabric, evictable, current, cat)
    if review.applied:
        moved = set(review.evicted)
        databricks.extend(w for w in cat.workloads if w.id in moved)
        current = size_capacity(fabric, cat)

    fabric_ids = {w.id for w in fabric}
    databricks_ids = {w.id for w in databricks}

    placements: list[Placement] = []
    for w in cat.workloads:
        eliminated, notes, flags = assessments[w.id]
        if w.id in fabric_ids:
            platform = Platform.FABRIC
        elif w.id in databricks_ids:
            platform = Platform.DATABRICKS
        else:
            platform = Platform.STAY_ON_SYNAPSE

        if platform is Platform.STAY_ON_SYNAPSE:
            rule_id = "R1-R5"
            reason = (
                "Every candidate was eliminated by a constraint. The honest answer is that "
                "this workload does not have a target yet — change a constraint or accept "
                "that it stays where it is. A plan that quietly assigns it anyway is a plan "
                "that fails in year two"
            )
            surface = "synapse"
        else:
            surface = cat.platforms.spec(platform).surfaces[w.kind]
            if w.id in review.evicted and review.applied:
                rule_id = "R8"
                reason = (
                    f"Moved off Fabric so the estate could drop to F{review.considered_sku}: "
                    f"its metered cost is less than the rung it was holding up"
                )
            elif w in forced_fabric or w in forced_databricks:
                rule_id = "R1-R5"
                other = Platform.DATABRICKS if platform is Platform.FABRIC else Platform.FABRIC
                reason = f"Only surviving platform — {eliminated[other]}"
            elif _fabric_pref(w, cat) and platform is Platform.FABRIC:
                rule_id = "R6"
                reason = (
                    "Direct Lake: the semantic model reads Delta in OneLake with no import "
                    "refresh to fail and no DirectQuery round trip. "
                    + r7_reason.get(w.id, "")
                )
            else:
                rule_id = "R7"
                reason = r7_reason.get(w.id, "Cheapest surviving platform")

        placements.append(
            Placement(
                workload_id=w.id,
                name=w.name,
                domain=w.domain,
                kind=w.kind,
                platform=platform,
                surface=surface,
                rule_id=rule_id,
                reason=reason,
                eliminated=eliminated,
                databricks_eur_month=databricks_run_eur_month(w, cat),
                fabric_cu_hours=fabric_demand(w, cat).compute_units,
                marginal_eur=marginal.get(w.id, 0.0) if platform is Platform.FABRIC else 0.0,
                migration_eur_month=(
                    0.0
                    if platform is Platform.STAY_ON_SYNAPSE
                    else migration_eur_month(w, platform, cat)
                ),
                notes=notes,
                flags=flags,
            )
        )

    return Plan(placements=placements, capacity=current, step_review=review, catalog=cat)
