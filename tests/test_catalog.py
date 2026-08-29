"""The configuration must be loadable, complete and internally consistent."""

from __future__ import annotations

import copy

import pytest

from azlake.catalog import CANDIDATES, Platform, load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_every_workload_has_a_surface_on_every_candidate(cat):
    for w in cat.workloads:
        for p in CANDIDATES:
            assert w.kind in cat.platforms.spec(p).surfaces


def test_workload_ids_are_unique(cat):
    ids = [w.id for w in cat.workloads]
    assert len(ids) == len(set(ids))


def test_the_target_region_is_one_a_platform_can_live_in(cat):
    assert cat.platforms.target_region in cat.platforms.fabric.capacity_regions


def test_stay_on_synapse_is_not_a_candidate(cat):
    assert Platform.STAY_ON_SYNAPSE not in CANDIDATES


def test_sku_ladder_is_sorted_and_positive(cat):
    skus = cat.costs.fabric.skus
    assert skus == sorted(skus)
    assert all(s > 0 for s in skus)


def test_streams_declare_an_event_rate(cat):
    for w in cat.workloads:
        if w.kind == "stream":
            assert w.events_per_second > 0, f"{w.id} is a stream with no event rate"


# ---------------------------------------------------------------------------
# The platform registry — data, not code (ADR-0005, ADR-0007)
# ---------------------------------------------------------------------------


def test_there_are_three_candidates_and_two_of_them_are_meters(cat):
    assert len(CANDIDATES) == 3
    assert set(cat.metered_platforms) == {Platform.DATABRICKS, Platform.SNOWFLAKE}


def test_exactly_one_platform_is_priced_as_a_capacity(cat):
    """The asymmetry the whole repo is about, asserted rather than assumed."""
    assert cat.capacity_platform is Platform.FABRIC
    assert not cat.platforms.spec(Platform.FABRIC).is_metered


def test_two_capacity_platforms_is_refused_rather_than_guessed_at(cat):
    """Two interacting ladders is a different problem, and the code says so."""
    broken = copy.deepcopy(cat)
    broken.platforms.platforms["databricks"].pricing = "capacity"
    with pytest.raises(ValueError, match="exactly one capacity-priced platform"):
        _ = broken.capacity_platform


def test_every_metered_candidate_has_a_meter_behind_it(cat):
    """A metered platform with no cost entry would cost €0 and win everything."""
    for p in cat.metered_platforms:
        meter = cat.costs.meter(p)
        assert meter.unit
        assert meter.eur_per_unit


def test_every_candidate_carries_a_platform_overhead(cat):
    for p in CANDIDATES:
        assert p.key in cat.costs.platform_overhead_eur_per_month


def test_a_candidate_with_no_configuration_fails_loudly(cat):
    """A candidate the config forgot must raise, not silently behave as absent."""
    broken = copy.deepcopy(cat)
    del broken.platforms.platforms["snowflake"]
    with pytest.raises(KeyError, match="SNOWFLAKE"):
        broken.platforms.spec(Platform.SNOWFLAKE)


def test_a_metered_candidate_with_no_meter_fails_loudly(cat):
    broken = copy.deepcopy(cat)
    del broken.costs.metered["snowflake"]
    with pytest.raises(KeyError, match="no meter"):
        broken.costs.meter(Platform.SNOWFLAKE)
