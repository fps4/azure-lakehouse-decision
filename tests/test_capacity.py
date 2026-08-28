"""The step function, and the two allowances that size it."""

from __future__ import annotations

import pytest

from azlake.capacity import marginal_eur, size_capacity
from azlake.catalog import load_catalog


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_an_empty_capacity_costs_nothing(cat):
    plan = size_capacity([], cat)
    assert plan.sku is None
    assert plan.monthly_eur == 0.0


def test_the_sku_is_the_first_rung_that_clears_the_requirement(cat):
    plan = size_capacity(cat.workloads, cat)
    skus = sorted(cat.costs.fabric.skus)
    assert plan.sku >= plan.required_cu
    below = [s for s in skus if s < plan.sku]
    assert not below or below[-1] < plan.required_cu


def test_headroom_makes_the_sized_capacity_larger_than_the_demand(cat):
    plan = size_capacity(cat.workloads, cat)
    assert plan.required_cu > plan.sustained_cu
    assert plan.utilisation < 1.0


def test_the_binding_allowance_is_reported(cat):
    plan = size_capacity(cat.workloads, cat)
    assert plan.binding in {"total", "interactive"}


def test_adding_a_workload_is_free_until_it_is_not(cat):
    """The whole thesis, as an assertion.

    Against an under-filled capacity, a small workload costs nothing and a large one
    costs a full rung. If either half of that ever stops being true, the cost model
    has stopped modelling a capacity and become a price list.

    The base is deliberately the pipelines — the smallest demand in the estate — so
    the capacity has room. Measured from the *plan's* Fabric set this would fail,
    and correctly: R7 fills the capacity until the next workload steps it, which is
    exactly what leaves the finished plan sitting against a boundary.
    """
    base_workloads = [w for w in cat.workloads if w.kind == "pipeline"]
    base = size_capacity(base_workloads, cat)

    small = cat.workload("DIM_ACCOUNT")
    large = cat.workload("NB_TELEMETRY_ROLLUP")

    free = marginal_eur(base, size_capacity([*base_workloads, small], cat))
    stepped = marginal_eur(base, size_capacity([*base_workloads, large], cat))

    assert free == 0.0, "a small workload did not ride free — this is not a capacity"
    assert stepped > 0.0, "a large workload did not force a rung — this is not a ladder"


def test_a_fabric_workload_has_no_standalone_price(cat):
    """Two identical additions to different capacities cost different amounts."""
    small = [w for w in cat.workloads if w.kind == "pipeline"]
    big = cat.workloads[:12]
    probe = next(w for w in cat.workloads if w.kind == "spark_notebook")
    a = marginal_eur(size_capacity(small, cat), size_capacity([*small, probe], cat))
    b = marginal_eur(size_capacity(big, cat), size_capacity([*big, probe], cat))
    assert a != b
