"""One test per rule, so a change to the rule set has to be deliberate."""

from __future__ import annotations

import copy

import pytest

from azlake.catalog import CANDIDATES, Platform, load_catalog
from azlake.econ import metered_run_eur_month
from azlake.rules import assess, build_plan


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def plan(cat):
    return build_plan(cat)


def _eliminated(cat, workload_id, platform):
    return platform in assess(cat.workload(workload_id), cat)[0]


def test_r1_restricted_data_only_goes_to_the_cleared_platform(cat):
    # HR sits under a stricter clearance, and no price may buy its way past it —
    # on either meter.
    assert _eliminated(cat, "VW_HR_HEADCOUNT", Platform.DATABRICKS)
    assert _eliminated(cat, "VW_HR_HEADCOUNT", Platform.SNOWFLAKE)
    assert not _eliminated(cat, "VW_HR_HEADCOUNT", Platform.FABRIC)


def test_r2_a_transactional_tsql_surface_eliminates_every_platform_without_one(cat):
    for platform in (Platform.DATABRICKS, Platform.SNOWFLAKE):
        assert _eliminated(cat, "FCT_GL_POSTING", platform)
        assert "[R2]" in assess(cat.workload("FCT_GL_POSTING"), cat)[0][platform]


def test_r2_a_plain_query_surface_eliminates_nothing(cat):
    # The rule is about transactions and procedures, not about SQL.
    for platform in (Platform.DATABRICKS, Platform.SNOWFLAKE):
        assert not _eliminated(cat, "FCT_INVENTORY_SNAP", platform)


def test_r3_event_time_restatement_eliminates_the_ingestion_time_engines(cat):
    # Two of the three aggregate by ingestion time, for different product reasons,
    # and R3 cannot tell those reasons apart — which is right, because the workload
    # cannot either.
    for platform in (Platform.FABRIC, Platform.SNOWFLAKE):
        assert _eliminated(cat, "STR_INVENTORY_MOVE", platform)
        assert "[R3]" in assess(cat.workload("STR_INVENTORY_MOVE"), cat)[0][platform]


def test_the_ladder_short_circuits_at_the_first_rule_that_fires(cat):
    """STR_PAYMENTS fails R3 on Snowflake too — but R1 gets there first, and says so.

    The reason a workload was eliminated has to be the *first* one, not the most
    interesting one. A register that reported the streaming gap here would send
    someone off to solve the wrong problem: fixing the semantics would not make
    this workload eligible, because the clearance would still stop it.
    """
    reason = assess(cat.workload("STR_PAYMENTS"), cat)[0][Platform.SNOWFLAKE]
    assert "[R1]" in reason
    assert "restricted" in reason


def test_r4_subsecond_telemetry_eliminates_the_other_direction(cat):
    for platform in (Platform.DATABRICKS, Platform.SNOWFLAKE):
        assert _eliminated(cat, "STR_DEVICE_TELEMETRY", platform)
        assert "[R4]" in assess(cat.workload("STR_DEVICE_TELEMETRY"), cat)[0][platform]


def test_r5_ml_lifecycle_leaves_exactly_one_platform_standing(cat):
    assert _eliminated(cat, "NB_DEMAND_FORECAST", Platform.FABRIC)
    assert _eliminated(cat, "NB_DEMAND_FORECAST", Platform.SNOWFLAKE)
    assert not _eliminated(cat, "NB_DEMAND_FORECAST", Platform.DATABRICKS)


def test_a_workload_with_no_surviving_platform_stays_on_synapse(plan):
    held = [p for p in plan.placements if p.platform is Platform.STAY_ON_SYNAPSE]
    assert [p.workload_id for p in held] == ["STR_PAYMENTS"]
    # And it is held for *different* reasons pointing opposite ways, which is the
    # whole reason it is interesting rather than a data error. Adding a third
    # candidate did not rescue it: the third one fails it the same way the first
    # does.
    p = held[0]
    assert "[R3]" in p.eliminated[Platform.FABRIC]
    assert "[R1]" in p.eliminated[Platform.DATABRICKS]
    assert "[R1]" in p.eliminated[Platform.SNOWFLAKE]


def test_constraints_are_never_overruled_by_economics(cat, plan):
    """The load-bearing invariant. If this ever fails, the design has changed."""
    for p in plan.placements:
        for platform, _ in p.eliminated.items():
            assert p.platform is not platform, (
                f"{p.workload_id} was placed on a platform its constraints eliminated"
            )


def test_r7_places_a_free_workload_into_paid_for_headroom(plan):
    # A workload the capacity absorbs costs nothing at the margin, and that is the
    # only reason it is on Fabric rather than metered.
    rollup = next(p for p in plan.placements if p.workload_id == "NB_TELEMETRY_ROLLUP")
    assert rollup.platform is Platform.FABRIC
    assert rollup.marginal_eur == 0.0
    assert all(v > 0.0 for v in rollup.metered_eur_month.values())


def test_r7_refuses_a_workload_that_would_force_a_step(plan):
    curation = next(p for p in plan.placements if p.workload_id == "NB_SALES_CURATION")
    assert curation.platform is Platform.DATABRICKS
    assert "rung" in curation.reason or "step" in curation.reason


def test_r7_compares_every_surviving_meter_and_says_what_it_turned_down(plan):
    """A choice that does not name the runner-up is not reviewable."""
    curation = next(p for p in plan.placements if p.workload_id == "NB_SALES_CURATION")
    assert set(curation.metered_eur_month) == {Platform.DATABRICKS, Platform.SNOWFLAKE}
    assert "Snowflake" in curation.reason
    # And it chose the cheaper of the two, which for Spark-shaped work is not the
    # warehouse-shaped platform.
    assert (
        curation.metered_eur_month[Platform.DATABRICKS]
        < curation.metered_eur_month[Platform.SNOWFLAKE]
    )


def test_the_answer_is_a_split_and_not_a_landslide(plan):
    fabric = plan.by_platform(Platform.FABRIC)
    metered = [p for p in plan.placements if p.platform in (Platform.DATABRICKS,
                                                            Platform.SNOWFLAKE)]
    assert fabric and metered, "a plan that picks one platform for everything is a red flag"


def test_the_plan_is_deterministic(cat):
    a = [(p.workload_id, p.platform) for p in build_plan(cat).placements]
    b = [(p.workload_id, p.platform) for p in build_plan(cat).placements]
    assert a == b


# ---------------------------------------------------------------------------
# The third platform, and the question it forces
# ---------------------------------------------------------------------------


def test_snowflake_prices_best_exactly_where_it_is_not_allowed_to_compete(cat, plan):
    """The finding this estate actually produces, pinned so it cannot drift silently.

    Snowflake is the cheapest meter for the dedicated SQL pool — and R2 eliminates
    it from every one of those workloads bar one, because they are written in
    T-SQL. A capability matrix cannot reach this conclusion (it has no prices) and
    a price table cannot either (it has no constraints). It needs both in the same
    sentence, which is the argument for having an engine at all.
    """
    cheapest_on = [
        p
        for p in plan.placements
        if min(p.metered_eur_month, key=lambda k: p.metered_eur_month[k]) is Platform.SNOWFLAKE
    ]
    assert cheapest_on, "Snowflake should price best somewhere or it is decoration"
    assert all(p.kind == "dedicated_sql" for p in cheapest_on)

    barred = [p for p in cheapest_on if Platform.SNOWFLAKE in p.eliminated]
    assert len(barred) >= 4
    assert all("[R2]" in p.eliminated[Platform.SNOWFLAKE] for p in barred)


def test_a_platform_that_wins_nothing_is_still_reported(plan):
    """A shut-out is a result, not an absence, and has to survive into the report."""
    from azlake.report import _plan_markdown

    assert not plan.by_platform(Platform.SNOWFLAKE)
    md = _plan_markdown(plan)
    assert "Snowflake" in md
    assert "won nothing" in md


def test_r9_closes_a_platform_that_cannot_pay_its_own_overhead(cat):
    """R9, on a catalog built to make it fire.

    The default estate never opens Snowflake, so the rule would otherwise ship
    untested. Here Snowpark is made cheap enough that R7 sends the notebooks to
    Snowflake on consumption alone — and R9 then asks the question R7 structurally
    cannot: was opening a whole platform for them worth €1,200/month?
    """
    tuned = copy.deepcopy(cat)
    snow = tuned.costs.metered["snowflake"]
    snow.units_per_compute_hour["snowpark"] = 0.30
    snow.units_per_tb_scanned["snowpark"] = 0.10

    plan = build_plan(tuned)
    review = next(r for r in plan.portfolio_reviews if r.platform is Platform.SNOWFLAKE)

    # It won workloads on the meter...
    assert review.workload_ids
    assert review.metered_eur < review.overhead_eur + review.rehome_eur
    # ...and still lost the estate, because the overhead is not divisible.
    assert review.closed
    assert not plan.by_platform(Platform.SNOWFLAKE)
    assert "overhead" in review.reason

    # Every workload it held ended up somewhere its constraints allow.
    for wid in review.workload_ids:
        p = next(x for x in plan.placements if x.workload_id == wid)
        assert p.platform is not Platform.SNOWFLAKE
        assert Platform.SNOWFLAKE not in {p.platform}
        assert p.rule_id == "R9" or p.platform is not Platform.SNOWFLAKE


def test_r9_keeps_a_platform_that_does_pay_its_own_overhead(cat):
    """The mirror case: cheap enough to be worth its own contract, and kept."""
    tuned = copy.deepcopy(cat)
    snow = tuned.costs.metered["snowflake"]
    snow.units_per_compute_hour["snowpark"] = 0.05
    snow.units_per_tb_scanned["snowpark"] = 0.02
    tuned.costs.platform_overhead_eur_per_month["snowflake"] = 50.0

    plan = build_plan(tuned)
    review = next(r for r in plan.portfolio_reviews if r.platform is Platform.SNOWFLAKE)
    assert not review.closed
    assert plan.by_platform(Platform.SNOWFLAKE)
    assert "earns its overhead" in review.reason


def test_r9_may_not_review_a_platform_a_constraint_pinned_a_workload_to(cat, plan):
    """Constraints outrank economics even when the economics is about a platform.

    Databricks holds workloads that survive nowhere else, so its overhead is not a
    choice and R9 has nothing to review. Saying that out loud is the point: an
    unreviewed platform must be unreviewed for a reason.
    """
    assert plan.by_platform(Platform.DATABRICKS)
    assert not any(r.platform is Platform.DATABRICKS for r in plan.portfolio_reviews)
    pinned = [
        p
        for p in plan.placements
        if p.platform is Platform.DATABRICKS
        and set(CANDIDATES) - set(p.eliminated) == {Platform.DATABRICKS}
    ]
    assert pinned, "Databricks is only unreviewable if something is genuinely pinned to it"


def test_the_overhead_of_every_platform_operated_reaches_the_bill(plan, cat):
    expected = sum(cat.costs.overhead(p) for p in plan.platforms_in_use)
    assert plan.platform_overhead_eur == expected
    assert plan.platform_overhead_eur > 0
    # And a platform nobody uses is not billed for.
    assert cat.costs.overhead(Platform.SNOWFLAKE) not in (plan.platform_overhead_eur,)


def test_a_metered_workload_costs_what_its_own_meter_says(plan, cat):
    """The straight line is true standing alone — that is what makes it a meter."""
    for p in plan.placements:
        if p.platform in cat.metered_platforms:
            w = cat.workload(p.workload_id)
            assert p.run_eur_month == pytest.approx(
                metered_run_eur_month(w, p.platform, cat)
            )
