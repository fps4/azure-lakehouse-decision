"""The configuration must be loadable, complete and internally consistent."""

from __future__ import annotations

import pytest

from azlake.catalog import CANDIDATES, Platform, load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_every_workload_has_a_surface_on_both_platforms(cat):
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
