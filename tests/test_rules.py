"""One test per rule, so a change to the rule set has to be deliberate."""

from __future__ import annotations

import pytest

from azlake.catalog import Platform, load_catalog
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
    # HR sits under a stricter clearance, and no price may buy its way past it.
    assert _eliminated(cat, "VW_HR_HEADCOUNT", Platform.DATABRICKS)
    assert not _eliminated(cat, "VW_HR_HEADCOUNT", Platform.FABRIC)


def test_r2_a_transactional_tsql_surface_eliminates_a_platform_without_one(cat):
    assert _eliminated(cat, "FCT_GL_POSTING", Platform.DATABRICKS)
    reason = assess(cat.workload("FCT_GL_POSTING"), cat)[0][Platform.DATABRICKS]
    assert "[R2]" in reason


def test_r2_a_plain_query_surface_eliminates_nothing(cat):
    # The rule is about transactions and procedures, not about SQL.
    assert not _eliminated(cat, "FCT_INVENTORY_SNAP", Platform.DATABRICKS)


def test_r3_event_time_restatement_eliminates_the_ingestion_time_engine(cat):
    assert _eliminated(cat, "STR_PAYMENTS", Platform.FABRIC)
    assert "[R3]" in assess(cat.workload("STR_PAYMENTS"), cat)[0][Platform.FABRIC]


def test_r4_subsecond_telemetry_eliminates_the_other_direction(cat):
    assert _eliminated(cat, "STR_DEVICE_TELEMETRY", Platform.DATABRICKS)
    assert "[R4]" in assess(cat.workload("STR_DEVICE_TELEMETRY"), cat)[0][Platform.DATABRICKS]


def test_r5_ml_lifecycle_eliminates_fabric_for_the_one_ml_workload(cat):
    assert _eliminated(cat, "NB_DEMAND_FORECAST", Platform.FABRIC)


def test_a_workload_with_no_surviving_platform_stays_on_synapse(plan):
    held = [p for p in plan.placements if p.platform is Platform.STAY_ON_SYNAPSE]
    assert [p.workload_id for p in held] == ["STR_PAYMENTS"]
    # And it is held for two *different* reasons pointing opposite ways, which is
    # the whole reason it is interesting rather than a data error.
    p = held[0]
    assert "[R3]" in p.eliminated[Platform.FABRIC]
    assert "[R1]" in p.eliminated[Platform.DATABRICKS]


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
    assert rollup.databricks_eur_month > 0.0


def test_r7_refuses_a_workload_that_would_force_a_step(plan):
    curation = next(p for p in plan.placements if p.workload_id == "NB_SALES_CURATION")
    assert curation.platform is Platform.DATABRICKS
    assert "rung" in curation.reason or "step" in curation.reason


def test_the_answer_is_a_split_and_not_a_landslide(plan):
    fabric = plan.by_platform(Platform.FABRIC)
    databricks = plan.by_platform(Platform.DATABRICKS)
    assert fabric and databricks, "a plan that picks one platform for everything is a red flag"


def test_the_plan_is_deterministic(cat):
    a = [(p.workload_id, p.platform) for p in build_plan(cat).placements]
    b = [(p.workload_id, p.platform) for p in build_plan(cat).placements]
    assert a == b
