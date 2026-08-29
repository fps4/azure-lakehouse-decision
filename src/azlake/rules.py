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
    R9  platform portfolio review    did every platform we opened pay for itself?
    R10 locality                     advisory: shortcut, do not copy

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

R8 and R9 exist because R7 is greedy, and a greedy rule is blind to exactly two
things — both of them costs that are not divisible by workload:

* **R8** — the capacity is a ladder. R7 fills the rung it is standing on and stops,
  which can leave the estate one rung too high for the sake of a few batch jobs.
* **R9** — a platform costs money to *operate*, not merely to consume. R7 places
  one workload at a time and can therefore open a whole platform for a workload
  that saves €200/month against an overhead of €1,200. With one metered platform
  that question never came up. With two it is the first thing a reviewer asks
  (ADR-0007).
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
from .econ import (
    cheapest_metered,
    fabric_demand,
    metered_quotes,
    metered_run_eur_month,
    migration_eur_month,
)


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
    #: Every meter's standalone price for this workload — the chosen one and the
    #: rejected ones, because a decision that hides what it turned down is not
    #: reviewable.
    metered_eur_month: dict[Platform, float] = field(default_factory=dict)
    fabric_cu_hours: float = 0.0
    marginal_eur: float = 0.0
    migration_eur_month: float = 0.0
    notes: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def run_eur_month(self) -> float:
        """What this workload adds to the monthly run bill, on the platform chosen.

        On a metered platform that is its metered cost. On Fabric it is its
        *marginal* cost — zero when the capacity absorbed it, the price of a rung
        when it did not. A Fabric workload showing €0 is not free: it is riding
        capacity the estate already pays for, and `reports/plan.md` totals the
        capacity separately so that nobody reads the zero as an absence.
        """
        if self.platform is Platform.FABRIC:
            return self.marginal_eur
        return self.metered_eur_month.get(self.platform, 0.0)


@dataclass
class StepReview:
    """R8 — whether the capacity that came out of R7 is the one to own."""

    considered_sku: int | None
    evicted: list[str]
    saving_eur: float
    added_metered_eur: float
    net_eur: float
    applied: bool
    reason: str


@dataclass
class PortfolioReview:
    """R9 — whether every platform the plan opened is worth operating.

    One of these per metered platform that R7 opened on economics alone. A platform
    that R1–R5 pinned a workload onto is not reviewable and does not appear here:
    its overhead is not a choice.
    """

    platform: Platform
    workload_ids: list[str]
    metered_eur: float
    overhead_eur: float
    rehome_eur: float
    net_eur: float
    closed: bool
    reason: str


@dataclass
class Plan:
    placements: list[Placement]
    capacity: CapacityPlan
    step_review: StepReview
    portfolio_reviews: list[PortfolioReview]
    catalog: Catalog

    def by_platform(self, platform: Platform) -> list[Placement]:
        return [p for p in self.placements if p.platform is platform]

    @property
    def platforms_in_use(self) -> list[Platform]:
        return [p for p in CANDIDATES if self.by_platform(p)]

    @property
    def platform_overhead_eur(self) -> float:
        """Every platform operated costs this whether or not it is busy.

        It is the number "just use whichever is cheapest per workload" forgets, and
        the reason R9 has to run after the allocation rather than during it.
        """
        return sum(self.catalog.costs.overhead(p) for p in self.platforms_in_use)

    def metered_run_eur(self, platform: Platform) -> float:
        return sum(p.run_eur_month for p in self.by_platform(platform))

    @property
    def metered_run_eur_total(self) -> float:
        return sum(self.metered_run_eur(p) for p in self.catalog.metered_platforms)

    @property
    def run_eur_month(self) -> float:
        return (
            self.capacity.total_eur
            + self.metered_run_eur_total
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
                and platform.key != pol.residency.cleared_platform_for_restricted
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

    # ---- R10 · advisory, and only advisory --------------------------------------
    survivors = [p for p in CANDIDATES if p not in eliminated]
    if len(survivors) > 1 and w.size_gb > 0:
        names = ", ".join(cat.platforms.spec(p).name for p in survivors)
        notes.append(
            f"Eligible for {len(survivors)} platforms ({names}). If it lands away from the "
            "rest of its domain, shortcut the storage rather than copying it — a second "
            "physical copy is the cost that never appears in any platform's bill."
        )
    return eliminated, notes, flags


# ---------------------------------------------------------------------------
# R6–R9 · placement, against a capacity that moves
# ---------------------------------------------------------------------------


def _fabric_pref(w: Workload, cat: Catalog) -> bool:
    """R6 — does this workload buy something on Fabric the meters cannot sell?"""
    return (
        cat.policy.semantics.prefer_direct_lake_consumers
        and w.consumer == "powerbi_direct_lake"
        and cat.platforms.fabric.capability.powerbi_direct_lake
    )


def _survivors(assessments: dict[str, tuple], w: Workload) -> list[Platform]:
    eliminated, _, _ = assessments[w.id]
    return [p for p in CANDIDATES if p not in eliminated]


def _step_review(
    fabric: list[Workload],
    evictable: list[Workload],
    plan: CapacityPlan,
    survivors: dict[str, list[Platform]],
    cat: Catalog,
) -> tuple[StepReview, list[Workload], dict[str, Platform]]:
    """R8 — the capacity we sized is on a ladder. Is the rung below cheaper to own?

    R7 fills a capacity greedily and stops. That is the right local move and it can
    still leave the estate one rung too high: a handful of batch workloads pushed
    the requirement past a boundary, and their metered cost elsewhere is less than
    the rung they bought. This checks, and prints the answer either way — including
    when the answer is "you cannot get there from here", which is the more common
    one and the more useful.

    Where an evicted workload goes is a question with more than one answer now, so
    it is asked properly: each one is re-homed to its own cheapest surviving meter,
    not to a default second choice.
    """
    skus = sorted(cat.costs.fabric.skus)
    if plan.sku is None or plan.sku == skus[0]:
        return (
            StepReview(None, [], 0.0, 0.0, 0.0, False, "already on the lowest rung"),
            fabric,
            {},
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
            {},
        )

    def best_meter(w: Workload) -> tuple[Platform, float] | None:
        pool = tuple(p for p in survivors[w.id] if p in cat.metered_platforms)
        return cheapest_metered(w, cat, among=pool)

    # Evict in order of cheapest metered cost per capacity unit freed: the best
    # exchange rate first. Direct Lake consumers go last and have to clear a higher
    # bar, which is R6 doing its work in the only place it can.
    def rate(w: Workload) -> tuple[int, float]:
        cu = fabric_demand(w, cat).compute_units or 1e-9
        quote = best_meter(w)
        price = quote[1] if quote else float("inf")
        return (1 if _fabric_pref(w, cat) else 0, price / cu)

    remaining = list(fabric)
    evicted: list[Workload] = []
    destination: dict[str, Platform] = {}
    for w in sorted(evictable, key=rate):
        if size_capacity(remaining, cat).required_cu <= lower:
            break
        quote = best_meter(w)
        if quote is None:
            # Nowhere to evict it to. It is on Fabric because Fabric is the only
            # platform it survived, and R8 may not overrule R1–R5.
            continue
        remaining = [x for x in remaining if x.id != w.id]
        evicted.append(w)
        destination[w.id] = quote[0]

    after = size_capacity(remaining, cat)
    if after.required_cu > lower or not evicted:
        return (
            StepReview(lower, [], 0.0, 0.0, 0.0, False, f"F{lower} not reachable by eviction"),
            fabric,
            {},
        )

    saving = plan.monthly_eur - after.monthly_eur
    added = sum(metered_run_eur_month(w, destination[w.id], cat) for w in evicted)
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
        return (
            StepReview(lower, [w.id for w in evicted], saving, added, net, True, reason),
            remaining,
            destination,
        )

    reason = (
        f"F{lower} is reachable but not worth it: it would save €{saving:,.0f}/month and "
        f"cost €{added:,.0f}/month in metered compute. The capacity is priced correctly at "
        f"F{plan.sku}"
    )
    return (
        StepReview(lower, [w.id for w in evicted], saving, added, net, False, reason),
        fabric,
        {},
    )


def _portfolio_review(
    assigned: dict[str, Platform],
    pinned: set[Platform],
    survivors: dict[str, list[Platform]],
    fabric: list[Workload],
    cat: Catalog,
) -> tuple[list[PortfolioReview], dict[str, Platform], list[Workload], dict[str, float]]:
    """R9 — did every platform this plan opened carry enough to pay for itself?

    The question a third platform forces and a second one never did. R7 places one
    workload at a time and can only ever see that workload's consumption, so it will
    happily open a whole platform because one workload saves €200/month on the
    meter. The overhead of operating that platform — contract, landing zone,
    identity, network, the people who know it — is not divisible by workload and is
    therefore invisible to a per-workload rule. It is only visible here, once the
    whole allocation exists (ADR-0007).

    A platform is reviewable only if nothing was *pinned* to it by R1–R5. If some
    workload can go nowhere else, the overhead is not a choice and there is nothing
    to review. That asymmetry is deliberate: constraints still outrank economics,
    even when the economics is about a platform rather than a workload.
    """
    reviews: list[PortfolioReview] = []
    marginal: dict[str, float] = {}
    if not cat.policy.platforms.review_platform_overhead:
        return reviews, assigned, fabric, marginal

    assigned = dict(assigned)

    for platform in cat.metered_platforms:
        if platform in pinned and cat.policy.platforms.pinned_platforms_are_not_reviewable:
            continue
        residents = [cat.workload(wid) for wid, p in assigned.items() if p is platform]
        if not residents:
            continue

        metered = sum(metered_run_eur_month(w, platform, cat) for w in residents)
        overhead = cat.costs.overhead(platform)

        # What it would cost to put every one of them somewhere else. Fabric is
        # priced marginally against a capacity that grows as we go, because that is
        # the only honest way to price it — re-homing three workloads onto a
        # capacity is not three independent decisions.
        trial_fabric = list(fabric)
        current = size_capacity(trial_fabric, cat)
        rehome = 0.0
        moves: dict[str, Platform] = {}
        moved_marginal: dict[str, float] = {}
        possible = True

        for w in sorted(residents, key=lambda x: -metered_run_eur_month(x, platform, cat)):
            options: list[tuple[float, int, Platform]] = []
            others = tuple(
                p
                for p in survivors[w.id]
                if p is not platform and p in cat.metered_platforms
                # Only somewhere already open: closing one platform to open another
                # trades one overhead for another and is not a saving.
                and (p in pinned or any(q is p for q in assigned.values()))
            )
            quote = cheapest_metered(w, cat, among=others)
            if quote is not None:
                options.append((quote[1], CANDIDATES.index(quote[0]), quote[0]))
            if Platform.FABRIC in survivors[w.id]:
                candidate = size_capacity([*trial_fabric, w], cat)
                options.append(
                    (
                        candidate.monthly_eur - current.monthly_eur,
                        CANDIDATES.index(Platform.FABRIC),
                        Platform.FABRIC,
                    )
                )
            if not options:
                possible = False
                break
            price, _, target = min(options)
            rehome += price
            moves[w.id] = target
            if target is Platform.FABRIC:
                # Record what it actually added to the capacity. Zero when the
                # capacity absorbed it — which is usually why re-homing is cheap.
                moved_marginal[w.id] = price
                trial_fabric.append(w)
                current = size_capacity(trial_fabric, cat)

        if not possible:
            reviews.append(
                PortfolioReview(
                    platform,
                    [w.id for w in residents],
                    metered,
                    overhead,
                    0.0,
                    0.0,
                    False,
                    (
                        f"{cat.platforms.spec(platform).name} cannot be closed: at least one "
                        f"of its workloads has nowhere else to go that survives R1–R5"
                    ),
                )
            )
            continue

        net = (metered + overhead) - rehome
        close = net > 0

        if close:
            reason = (
                f"{cat.platforms.spec(platform).name} carried {len(residents)} workload(s) "
                f"for €{metered:,.0f}/month of metered compute against €{overhead:,.0f}/month "
                f"of platform overhead. Re-homing them costs €{rehome:,.0f}/month, so closing "
                f"the platform saves €{net:,.0f}/month. A meter that wins on consumption can "
                f"still lose on the contract"
            )
            for wid, target in moves.items():
                assigned[wid] = target
            marginal.update(moved_marginal)
            fabric = trial_fabric
        else:
            reason = (
                f"{cat.platforms.spec(platform).name} earns its overhead: "
                f"€{metered:,.0f}/month metered plus €{overhead:,.0f}/month to operate, "
                f"against €{rehome:,.0f}/month to re-home its {len(residents)} workload(s) "
                f"elsewhere. Keeping it is €{-net:,.0f}/month better"
            )

        reviews.append(
            PortfolioReview(
                platform,
                [w.id for w in residents],
                metered,
                overhead,
                rehome,
                net,
                close,
                reason,
            )
        )

    return reviews, assigned, fabric, marginal


def build_plan(cat: Catalog) -> Plan:
    """Assess every workload, then place them against a capacity that changes."""
    assessments = {w.id: assess(w, cat) for w in cat.workloads}
    survivors = {w.id: _survivors(assessments, w) for w in cat.workloads}

    stranded: list[Workload] = []
    forced: dict[str, Platform] = {}
    free: list[Workload] = []

    for w in cat.workloads:
        surviving = survivors[w.id]
        if not surviving:
            stranded.append(w)
        elif len(surviving) == 1:
            forced[w.id] = surviving[0]
        else:
            free.append(w)

    # A platform some workload was *pinned* to by R1–R5. Its overhead is not a
    # choice, so R9 may not review it and R7 need not charge anyone for opening it.
    pinned = {p for p in forced.values()}

    # ---- R7 · economics, one workload at a time, against a moving capacity -----
    fabric: list[Workload] = [w for w in cat.workloads if forced.get(w.id) is Platform.FABRIC]
    assigned: dict[str, Platform] = dict(forced)
    current = size_capacity(fabric, cat)
    marginal: dict[str, float] = {w.id: 0.0 for w in fabric}
    r7_reason: dict[str, str] = {}

    def best_meter(w: Workload) -> tuple[Platform, float] | None:
        pool = tuple(p for p in survivors[w.id] if p in cat.metered_platforms)
        return cheapest_metered(w, cat, among=pool)

    # Biggest metered bill first: the workload with most to save is the one that
    # should get first claim on free headroom.
    def sort_key(w: Workload) -> tuple[float, str]:
        quote = best_meter(w)
        return (-(quote[1] if quote else 0.0), w.id)

    for w in sorted(free, key=sort_key):
        quote = best_meter(w)
        candidate = size_capacity(fabric + [w], cat)
        step = candidate.monthly_eur - current.monthly_eur

        if quote is None:
            # Fabric is the only survivor that can host it; R7 has no choice to make.
            fabric.append(w)
            assigned[w.id] = Platform.FABRIC
            marginal[w.id] = step
            current = candidate
            r7_reason[w.id] = "No surviving meter — Fabric is the only place it can go"
            continue

        meter, price = quote
        meter_name = cat.platforms.spec(meter).name
        bar = price * cat.policy.semantics.max_premium_ratio if _fabric_pref(w, cat) else price

        if step <= bar and Platform.FABRIC in survivors[w.id]:
            fabric.append(w)
            assigned[w.id] = Platform.FABRIC
            marginal[w.id] = step
            current = candidate
            if step == 0.0:
                r7_reason[w.id] = (
                    f"Absorbed by the F{current.sku} capacity already paid for — marginal "
                    f"cost €0 against €{price:,.0f}/month on {meter_name}, the cheapest "
                    f"meter that survived. Free headroom is the cheapest compute in the "
                    f"estate, and the only way to use it is to put something on it"
                )
            else:
                r7_reason[w.id] = (
                    f"Forces F{current.sku} at €{step:,.0f}/month, still under the "
                    f"€{bar:,.0f}/month bar set by {meter_name}"
                )
        else:
            assigned[w.id] = meter
            others = {
                p: v
                for p, v in metered_quotes(w, cat).items()
                if p is not meter and p in survivors[w.id]
            }
            versus = (
                "; ".join(
                    f"{cat.platforms.spec(p).name} €{v:,.0f}" for p, v in sorted(others.items())
                )
                or "no other meter survived"
            )
            if Platform.FABRIC in survivors[w.id]:
                r7_reason[w.id] = (
                    f"Would push the capacity to F{candidate.sku}, a step of "
                    f"€{step:,.0f}/month, against €{price:,.0f}/month on {meter_name} "
                    f"({versus}). The marginal workload that forces a rung pays for the "
                    f"whole rung"
                )
            else:
                r7_reason[w.id] = (
                    f"Cheapest surviving meter at €{price:,.0f}/month on {meter_name} "
                    f"({versus})"
                )

    # ---- R8 · is the rung we landed on the one to own? ------------------------
    evictable = [w for w in fabric if w in free]
    review, fabric, evicted_to = _step_review(fabric, evictable, current, survivors, cat)
    if review.applied:
        for wid, target in evicted_to.items():
            assigned[wid] = target
        current = size_capacity(fabric, cat)

    # ---- R9 · did every platform we opened pay for itself? --------------------
    reviews, assigned, fabric, rehomed_marginal = _portfolio_review(
        assigned, pinned, survivors, fabric, cat
    )
    marginal.update(rehomed_marginal)
    current = size_capacity(fabric, cat)
    fabric_ids = {w.id for w in fabric}

    placements: list[Placement] = []
    for w in cat.workloads:
        eliminated, notes, flags = assessments[w.id]
        platform = assigned.get(w.id, Platform.STAY_ON_SYNAPSE)
        if platform is Platform.FABRIC and w.id not in fabric_ids:
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
            was_moved_by_r9 = any(w.id in r.workload_ids for r in reviews if r.closed)
            if w.id in review.evicted and review.applied:
                rule_id = "R8"
                reason = (
                    f"Moved off Fabric so the estate could drop to F{review.considered_sku}: "
                    f"its metered cost is less than the rung it was holding up"
                )
            elif was_moved_by_r9:
                origin = next(r for r in reviews if r.closed and w.id in r.workload_ids)
                rule_id = "R9"
                reason = (
                    f"Re-homed to {cat.platforms.spec(platform).name}: "
                    f"{cat.platforms.spec(origin.platform).name} won it on the meter but "
                    f"could not cover its own €{origin.overhead_eur:,.0f}/month of platform "
                    f"overhead with the workloads it attracted"
                )
            elif w.id in forced:
                rule_id = "R1-R5"
                # Name each rejection by the rule that fired, not by repeating its
                # full text: with two other candidates the long form crowded the
                # decision out of its own row. The full reasons are listed once, in
                # the eliminations section of the report.
                grouped: dict[str, list[str]] = {}
                for p, why in eliminated.items():
                    grouped.setdefault(why.split("]")[0].lstrip("["), []).append(
                        cat.platforms.spec(p).name
                    )
                by_rule = "; ".join(
                    f"{rule} ruled out {' and '.join(names)}" for rule, names in grouped.items()
                )
                reason = f"Only surviving platform — {by_rule}"
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
                metered_eur_month=metered_quotes(w, cat),
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

    return Plan(
        placements=placements,
        capacity=current,
        step_review=review,
        portfolio_reviews=reviews,
        catalog=cat,
    )
