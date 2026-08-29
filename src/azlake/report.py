"""Rendering — the console summary, the plan, the ledger, and two charts.

One rule governs everything here (ADR-0006): a euro figure never appears without
the sentence that says where it came from. A number that travels without its
provenance is a number that ends up in a steering deck as a fact.

Nothing here hard-codes a platform list either. Labels and colours come from the
configured platforms, so a fourth target appears in every table and both charts
without an edit to this file (ADR-0007).
"""

from __future__ import annotations

from pathlib import Path

from .capacity import size_capacity
from .catalog import CANDIDATES, Catalog, Platform
from .econ import fabric_demand, metered_run_eur_month
from .rules import Plan

PLACEHOLDER = (
    "Every euro figure below is an **illustrative placeholder shaped like list "
    "pricing** — not a quote, not a rate card, not a client's contract. Replace "
    "`config/cost_model.yaml` with real numbers before any of it decides anything."
)

#: Short forms for the fixed-width console table. Anything not named here falls
#: back to the platform's own key, so a new platform is legible without an edit.
_SHORT_OVERRIDE = {
    Platform.FABRIC: "Fabric",
    Platform.DATABRICKS: "Databricks",
    Platform.SNOWFLAKE: "Snowflake",
    Platform.STAY_ON_SYNAPSE: "Synapse",
}

_CHART_COLOURS = {
    Platform.FABRIC: "#1f6feb",
    Platform.DATABRICKS: "#d97706",
    Platform.SNOWFLAKE: "#0ea5e9",
    Platform.STAY_ON_SYNAPSE: "#6b7280",
}


def _label(platform: Platform, cat: Catalog) -> str:
    """The long form — what a reader of `reports/plan.md` sees, as a phrase."""
    if platform is Platform.STAY_ON_SYNAPSE:
        return "stays on Synapse"
    return cat.platforms.spec(platform).name


def _short(platform: Platform) -> str:
    return _SHORT_OVERRIDE.get(platform, platform.key.title())


def _colour(platform: Platform) -> str:
    return _CHART_COLOURS.get(platform, "#64748b")


def console_summary(plan: Plan) -> str:
    cat = plan.catalog
    cap = plan.capacity
    lines: list[str] = []
    lines.append(
        f"ESTATE: {len(cat.workloads)} workloads · target region "
        f"{cat.platforms.target_region} · "
        f"{len(cat.metered_platforms) + 1} candidate platforms"
    )
    lines.append("")
    header = (
        f"{'WORKLOAD':<23}{'KIND':<17}{'PLATFORM':<12}{'SURFACE':<21}"
        f"{'CU-H/MO':>9}{'€/MO':>9}  WHY"
    )
    lines.append(header)
    lines.append("-" * 118)
    for p in plan.placements:
        why = p.reason.split(".")[0].split(" — ")[0]
        if len(why) > 34:
            why = why[:31] + "..."
        lines.append(
            f"{p.workload_id:<23}{p.kind:<17}{_short(p.platform):<12}{p.surface:<21}"
            f"{p.fabric_cu_hours:>9,.0f}{p.run_eur_month:>9,.0f}  [{p.rule_id}] {why}"
        )
    lines.append("")

    counts = {pl: len(plan.by_platform(pl)) for pl in Platform}
    lines.append(
        "MIX   " + "  ".join(f"{_short(pl).upper()}: {n}" for pl, n in counts.items() if n)
    )

    if cap.sku:
        lines.append(
            f"CAP   F{cap.sku} · {cap.sustained_cu:.1f} CU sustained of {cap.sku} "
            f"({cap.utilisation:.0%} used) · sized by the {cap.binding} allowance at "
            f"{cap.required_cu:.1f} CU required"
        )
    metered_parts = "  ".join(
        f"{_short(p)} €{plan.metered_run_eur(p):,.0f}"
        for p in cat.metered_platforms
        if plan.by_platform(p)
    )
    lines.append(
        f"RUN   €{plan.run_eur_month:,.0f}/month  "
        f"(capacity €{cap.total_eur:,.0f} · metered {metered_parts or '€0'} · "
        f"platform overhead €{plan.platform_overhead_eur:,.0f} across "
        f"{len(plan.platforms_in_use)} platforms)"
    )
    lines.append(
        f"MOVE  €{plan.migration_eur_month:,.0f}/month amortised over "
        f"{cat.costs.migration.amortise_months:.0f} months — "
        f"{plan.migration_eur_month / max(plan.total_eur_month, 1e-9):.0%} of the bill, and "
        f"almost identical on every target"
    )
    lines.append(f"R8    {plan.step_review.reason}")
    for r in plan.portfolio_reviews:
        lines.append(f"R9    {r.reason}")
    for pl in cat.metered_platforms:
        if plan.by_platform(pl):
            continue
        cheapest_on = [
            p
            for p in plan.placements
            if p.metered_eur_month
            and min(p.metered_eur_month, key=lambda k: p.metered_eur_month[k]) is pl
        ]
        barred = [p for p in cheapest_on if pl in p.eliminated]
        lines.append(
            f"NONE  {_short(pl)} won nothing: cheapest meter on {len(cheapest_on)} "
            f"workload(s), barred by a constraint on {len(barred)} of them. "
            f"See reports/plan.md"
        )

    stranded = plan.by_platform(Platform.STAY_ON_SYNAPSE)
    if stranded:
        lines.append(
            "HELD  "
            + ", ".join(p.workload_id for p in stranded)
            + " — no target survives its constraints"
        )
    return "\n".join(lines)


def _shutout(plan: Plan, platform: Platform) -> str | None:
    """Why a candidate that survived the constraints still won nothing.

    A platform can lose an estate in two entirely different ways, and a plan that
    reports only the headcount cannot tell them apart:

    * it was never the cheapest meter — it is simply the wrong shape for this work; or
    * it was the cheapest meter, repeatedly, **for workloads it was not allowed to
      have** — a constraint took exactly the rows its economics was best at.

    The second is the more useful finding and the one a capability matrix can never
    produce, because it needs the constraints and the prices in the same sentence.
    """
    cat = plan.catalog
    if plan.by_platform(platform) or platform not in cat.metered_platforms:
        return None

    cheapest_on = [
        p
        for p in plan.placements
        if p.metered_eur_month
        and min(p.metered_eur_month, key=lambda k: p.metered_eur_month[k]) is platform
    ]
    barred = [p for p in cheapest_on if platform in p.eliminated]
    lost_on_price = [p for p in cheapest_on if platform not in p.eliminated]
    survived = [p for p in plan.placements if platform not in p.eliminated]

    name = _label(platform, cat)
    if not cheapest_on:
        return (
            f"**{name} won nothing, and was never close.** It survived the constraints on "
            f"{len(survived)} of {len(plan.placements)} workloads and was not the cheapest "
            f"meter on any of them. That is a clean answer: for the work in this estate it "
            f"is the wrong shape, not merely the loser of a close call."
        )

    rules = sorted({p.eliminated[platform].split("]")[0].lstrip("[") for p in barred})
    parts = [
        f"**{name} won nothing — and it is the most interesting row in this plan.** "
        f"It was the cheapest meter on {len(cheapest_on)} of {len(plan.placements)} "
        f"workloads."
    ]
    if barred:
        ids = ", ".join(f"`{p.workload_id}`" for p in barred)
        parts.append(
            f"On {len(barred)} of those it is not allowed to compete: {ids} — eliminated by "
            f"{', '.join(rules)} before any price was looked at. **The workloads it prices "
            f"best are precisely the ones a constraint takes away from it**, which is a "
            f"conclusion neither a capability matrix nor a price table can reach on its own, "
            f"because each holds only half of it."
        )
    if lost_on_price:
        ids = ", ".join(f"`{p.workload_id}`" for p in lost_on_price)
        parts.append(
            f"On the remaining {len(lost_on_price)} ({ids}) it was allowed to compete and "
            f"still lost — not to the other meter, but to free capacity the estate had "
            f"already bought. A meter cannot underbid €0."
        )
    parts.append(
        "Worth being explicit about what this is not: it is not a verdict on the product. "
        "It is a verdict on this estate, whose expensive work is Spark-shaped and whose "
        "SQL-shaped work is locked to T-SQL. Change either fact and the answer moves."
    )
    return " ".join(parts)


def _plan_markdown(plan: Plan) -> str:
    cat = plan.catalog
    cap = plan.capacity
    out: list[str] = []
    out.append("# The plan\n")
    out.append("*Generated by `make decide`. Do not edit by hand.*\n")
    out.append(PLACEHOLDER + "\n")

    out.append("## Where the estate lands\n")
    counts = {pl: len(plan.by_platform(pl)) for pl in Platform}
    out.append("| Destination | Workloads |")
    out.append("|---|---|")
    for pl, n in counts.items():
        if n:
            out.append(f"| {_label(pl, cat)} | {n} |")
    out.append("")

    out.append("## The capacity\n")
    if cap.sku:
        out.append(
            f"**F{cap.sku}** — {cap.sustained_cu:.1f} CU sustained against a purchased "
            f"{cap.sku} CU, so **{cap.utilisation:.0%} of what is paid for is used** and "
            f"{cap.headroom_cu:.1f} CU sit idle.\n"
        )
        out.append(
            f"The rung was chosen by the **{cap.binding}** allowance: "
            f"{cap.required_cu:.1f} CU required after headroom, against "
            f"{cap.sustained_cu:.1f} CU of raw sustained demand "
            f"({cap.interactive_cu:.1f} CU of it interactive). Fabric smooths and then "
            f"throttles, so a capacity planned to its ceiling is a capacity that "
            f"throttles interactive users while background jobs catch up — which is why "
            f"the allowances exist and why the sized number is larger than the demand.\n"
        )
    out.append(f"**R8 · step-boundary review.** {plan.step_review.reason}.\n")

    out.append("## The platforms, and whether they paid for themselves\n")
    out.append(
        "A platform costs money to operate whether it is busy or not, and that cost is "
        "not divisible by workload. R7 places one workload at a time and cannot see it. "
        "R9 can, once the whole allocation exists — and it is the rule that only starts "
        "to matter when there is more than one meter to choose between "
        "([ADR-0007](../docs/design/decisions/0007-a-platform-costs-something-to-open.md)).\n"
    )
    out.append("| Platform | Workloads | Metered €/mo | Overhead €/mo | R9 |")
    out.append("|---|---:|---:|---:|---|")
    for pl in CANDIDATES:
        n = len(plan.by_platform(pl))
        metered = plan.metered_run_eur(pl) if pl in cat.metered_platforms else 0.0
        overhead = cat.costs.overhead(pl) if n else 0.0
        verdict = "nothing to review — it won no workloads, so it is not operated"
        for r in plan.portfolio_reviews:
            if r.platform is pl:
                verdict = "**closed**" if r.closed else "kept"
        if pl is cat.capacity_platform:
            verdict = "not reviewable — it is the capacity"
        elif n and not any(r.platform is pl for r in plan.portfolio_reviews):
            verdict = "not reviewable — R1–R5 pinned a workload to it"
        out.append(
            f"| {_label(pl, cat)} | {n} | "
            f"{'—' if pl is cat.capacity_platform else f'{metered:,.0f}'} | "
            f"{overhead:,.0f} | {verdict} |"
        )
    out.append("")
    for r in plan.portfolio_reviews:
        out.append(f"- **R9 · {_label(r.platform, cat)}.** {r.reason}.")
    for pl in CANDIDATES:
        shutout = _shutout(plan, pl)
        if shutout:
            out.append("")
            out.append(shutout)
    out.append("")

    out.append("## The bill\n")
    out.append("| Line | €/month | Note |")
    out.append("|---|---:|---|")
    out.append(
        f"| Fabric capacity (F{cap.sku}) | {cap.monthly_eur:,.0f} | "
        f"pre-paid; carries {len(plan.by_platform(Platform.FABRIC))} workloads |"
    )
    out.append(f"| Fabric storage | {cap.storage_eur:,.0f} | OneLake + Eventhouse hot cache |")
    for pl in cat.metered_platforms:
        n = len(plan.by_platform(pl))
        if not n:
            continue
        out.append(
            f"| {_label(pl, cat)} metered | {plan.metered_run_eur(pl):,.0f} | "
            f"{n} workloads, straight-line |"
        )
    out.append(
        f"| Platform overhead | {plan.platform_overhead_eur:,.0f} | "
        f"{len(plan.platforms_in_use)} platforms operated; paid per platform, "
        f"not per workload |"
    )
    out.append(f"| **Run, total** | **{plan.run_eur_month:,.0f}** | recurs forever |")
    out.append(
        f"| Migration, amortised | {plan.migration_eur_month:,.0f} | over "
        f"{cat.costs.migration.amortise_months:.0f} months |"
    )
    out.append(f"| **Total** | **{plan.total_eur_month:,.0f}** | |")
    out.append("")
    share = plan.migration_eur_month / max(plan.total_eur_month, 1e-9)
    out.append(
        f"The migration is **{share:.0%} of the bill over this horizon, and it is very "
        f"nearly the same number on every target** — it differs only where a T-SQL "
        f"surface would have to be rewritten rather than moved. The platform choice "
        f"moves the smaller half. That does not make it unimportant: run cost is the "
        f"half that never stops. But a platform argument that never says this out loud "
        f"is an argument with a missing premise.\n"
    )

    out.append("## Every workload, with the reason in the row\n")
    meters = list(cat.metered_platforms)
    meter_cols = " | ".join(f"{_short(p)} €/mo" for p in meters)
    out.append(f"| Workload | Kind | → | Surface | CU-h/mo | {meter_cols} | €/mo | Rule | Why |")
    out.append("|---|---|---|---|---:|" + "---:|" * len(meters) + "---:|---|---|")
    for p in plan.placements:
        quotes = " | ".join(f"{p.metered_eur_month.get(m, 0.0):,.0f}" for m in meters)
        out.append(
            f"| `{p.workload_id}` | {p.kind} | {_label(p.platform, cat)} | {p.surface} | "
            f"{p.fabric_cu_hours:,.0f} | {quotes} | {p.run_eur_month:,.0f} | {p.rule_id} | "
            f"{p.reason} |"
        )
    out.append("")
    out.append(
        "The two meter columns are what each workload would cost on that platform "
        "**standing alone**, and they are true in that form — that is what a meter is. "
        "The `CU-h/mo` column is not a price and cannot be turned into one: it is demand "
        "against a shared pool, and the pool is billed once, in the table above. A Fabric "
        "workload showing **€0** is not free, it is riding capacity the estate already "
        "pays for. That asymmetry between the columns is the whole reason this repo "
        "exists, and it is why these rows cannot be added up sideways.\n"
    )

    out.append("## What was ruled out, and by what\n")
    out.append(
        "Constraints eliminate; economics chooses. Everything in this section happened "
        "before any price was compared.\n"
    )
    for p in plan.placements:
        if not p.eliminated:
            continue
        out.append(f"**`{p.workload_id}`** — {p.name}")
        for platform, why in p.eliminated.items():
            out.append(f"- {_label(platform, cat)}: {why}")
        out.append("")

    return "\n".join(out)


def _chart_capacity(plan: Plan, path: Path) -> Path:
    """The step function against the straight lines.

    The one picture worth having. Everything else in this repo is an elaboration
    of the gap between these two shapes — and with two meters on the chart, of the
    gap between the meters themselves.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cat = plan.catalog
    c = cat.costs.fabric
    skus = sorted(c.skus)
    rate = c.effective_eur_per_cu_hour * cat.costs.hours_per_month

    all_fabric = size_capacity(cat.workloads, cat)
    top = max(all_fabric.required_cu, plan.capacity.required_cu) * 1.35

    # One horizontal segment per rung, over the range of demand that rung serves.
    # Consecutive segments share an x, which is what draws the riser between them.
    xs: list[float] = []
    ys: list[float] = []
    prev = 0.0
    highest = 0.0
    for sku in skus:
        if prev >= top:
            break
        xs.extend([prev, min(float(sku), top)])
        ys.extend([sku * rate, sku * rate])
        highest = sku * rate
        prev = float(sku)

    fig, ax = plt.subplots(figsize=(9.5, 5.4))
    ax.plot(xs, ys, linewidth=2.4, color=_colour(Platform.FABRIC),
            label="Fabric capacity — a step function")

    # Each metered alternative on the same axis, drawn as a straight line through
    # the estate's own point. The honest claim is "metered is linear", not "metered
    # is exactly this" — the conversion between a CU, a DBU and a credit is the
    # least defensible number in the repo (see config/cost_model.yaml).
    fab_cu = (
        sum(fabric_demand(w, cat).compute_units for w in cat.workloads)
        / cat.costs.hours_per_month
    )
    if fab_cu > 0:
        for pl in cat.metered_platforms:
            total = sum(metered_run_eur_month(w, pl, cat) for w in cat.workloads)
            slope = total / fab_cu
            ax.plot(
                [0, top],
                [0, slope * top],
                linewidth=2.0,
                color=_colour(pl),
                linestyle="--",
                label=f"{_short(pl)} metered — a straight line",
            )

    ax.set_ylim(0, highest * 1.18)
    ax.set_xlim(0, top)

    req = plan.capacity.required_cu
    sku_eur = (plan.capacity.sku or 0) * rate
    ax.axvline(req, color="#16a34a", linewidth=1.4, linestyle=":")
    # The rung the plan actually sits on, marked — the riser above it is the one it
    # avoided, and without a marker the two read as the same point.
    ax.plot([req], [sku_eur], "o", color="#16a34a", markersize=7, zorder=5)
    ax.annotate(
        f"this plan · F{plan.capacity.sku}\n{req:.1f} CU required, "
        f"{plan.capacity.utilisation:.0%} of the rung used",
        xy=(req, sku_eur),
        xytext=(req * 0.06, highest * 1.05),
        fontsize=9,
        color="#166534",
        arrowprops={"arrowstyle": "->", "color": "#16a34a", "linewidth": 1.0},
    )
    ax.axvline(all_fabric.required_cu, color="#9333ea", linewidth=1.2, linestyle=":")
    ax.plot(
        [all_fabric.required_cu],
        [(all_fabric.sku or 0) * rate],
        "o",
        color="#9333ea",
        markersize=7,
        zorder=5,
    )
    ax.annotate(
        f"everything on Fabric · F{all_fabric.sku}\n{all_fabric.required_cu:.1f} CU — "
        f"one rung higher, for the\nsake of the workloads R7 declined",
        xy=(all_fabric.required_cu, (all_fabric.sku or 0) * rate),
        xytext=(all_fabric.required_cu * 0.42, highest * 0.62),
        fontsize=9,
        color="#6b21a8",
        arrowprops={"arrowstyle": "->", "color": "#9333ea", "linewidth": 1.0},
    )

    ax.set_xlabel("sustained capacity required (CU, after headroom)")
    ax.set_ylabel(f"€/month ({cat.costs.currency}, illustrative)")
    ax.set_title("A step function against two straight lines")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right", fontsize=9)
    fig.text(
        0.5,
        0.005,
        "Illustrative placeholder pricing from config/cost_model.yaml — not a quote.",
        ha="center",
        fontsize=7.5,
        color="#6b7280",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def _chart_mix(plan: Plan, path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cat = plan.catalog
    kinds = ["dedicated_sql", "serverless_view", "spark_notebook", "pipeline", "stream"]
    order = [*CANDIDATES, Platform.STAY_ON_SYNAPSE]

    fig, ax = plt.subplots(figsize=(9, 4.4))
    bottom = [0.0] * len(kinds)
    for pl in order:
        vals = [
            float(sum(1 for p in plan.placements if p.platform is pl and p.kind == k))
            for k in kinds
        ]
        if not any(vals):
            continue
        ax.bar(kinds, vals, bottom=bottom, label=_label(pl, cat), color=_colour(pl))
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]

    ax.set_ylabel("workloads")
    ax.set_title("The answer is a split, and the split is not by preference")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def write_all(plan: Plan, reports_dir: Path | None = None) -> list[Path]:
    out = Path(reports_dir) if reports_dir else Path("reports")
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "plan.md"]
    (out / "plan.md").write_text(_plan_markdown(plan), encoding="utf-8")
    written.append(_chart_capacity(plan, out / "capacity-step.png"))
    written.append(_chart_mix(plan, out / "mix.png"))
    return written


def explain(plan: Plan, workload_id: str, cat: Catalog) -> str:
    """Everything the engine knows about one workload, including the roads not taken."""
    match = [p for p in plan.placements if p.workload_id == workload_id]
    if not match:
        known = ", ".join(p.workload_id for p in plan.placements)
        raise KeyError(f"unknown workload {workload_id!r}; known: {known}")
    p = match[0]
    w = cat.workload(workload_id)

    lines = [f"{p.workload_id} — {p.name}"]
    lines.append(f"  kind       {p.kind} · {w.consumer} · {w.latency_class}")
    lines.append(f"  decision   {_label(p.platform, cat)} / {p.surface}  (rule {p.rule_id})")
    lines.append(f"  because    {p.reason}")
    if p.eliminated:
        lines.append("  ruled out")
        for platform, why in p.eliminated.items():
            lines.append(f"    - {_label(platform, cat)}: {why}")
    fd = fabric_demand(w, cat)
    lines.append("  demand")
    lines.append(
        f"    {_short(Platform.FABRIC):<11} {fd.compute_units:,.0f} CU-h/mo "
        f"(compute {fd.from_compute:,.0f} · scan {fd.from_scan:,.0f} · "
        f"events {fd.from_events:,.0f}) + €{fd.storage_eur_month:,.0f}/mo storage — "
        f"demand on a shared pool, not a price"
    )
    for pl in cat.metered_platforms:
        lines.append(
            f"    {_short(pl):<11} €{p.metered_eur_month.get(pl, 0.0):,.0f}/mo metered, "
            f"standalone and true"
        )
    if p.platform is Platform.FABRIC:
        lines.append(
            f"    marginal    €{p.marginal_eur:,.0f}/mo — what it actually added to the "
            f"capacity, which is the only Fabric number that means anything per workload"
        )
    lines.append(f"  migration  €{p.migration_eur_month:,.0f}/mo amortised")
    for n in p.notes:
        lines.append(f"  note       {n}")
    if p.flags:
        lines.append(f"  flags      {', '.join(sorted(set(p.flags)))}")
    return "\n".join(lines)
