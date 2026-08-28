"""The simulations must keep demonstrating what the rules claim."""

from __future__ import annotations

import pytest

from azlake.sim.batch import run_batch
from azlake.sim.streaming import run_streaming


@pytest.fixture(scope="module")
def stream():
    return run_streaming()[0]


@pytest.fixture(scope="module")
def batch():
    return run_batch()


def test_the_event_time_shape_lands_exactly_on_the_truth(stream):
    assert stream.streaming_total_cents == stream.truth_total_cents
    assert stream.streaming_window_error_cents == 0


def test_the_ingestion_time_shape_double_counts_redeliveries(stream):
    assert stream.eventhouse_total_cents > stream.truth_total_cents
    assert stream.duplicates_counted_by_eventhouse > 0


def test_the_ingestion_time_shape_misplaces_late_events(stream):
    assert stream.eventhouse_window_error_cents > 0
    assert stream.late_events > 0


def test_the_event_time_shape_actually_restates_windows(stream):
    # If it never restated anything, the test above would be passing by accident.
    assert stream.restatements > 0


def test_a_transactional_load_survives_being_killed(batch):
    assert batch.warehouse_consistent_with_transaction


def test_the_same_load_without_transactions_does_not(batch):
    assert not batch.warehouse_consistent_without_transaction
    assert batch.torn_customers > 0


def test_the_idempotent_load_converges_on_a_retry(batch):
    assert batch.lakehouse_consistent_after_retry


def test_both_correct_shapes_agree_on_the_answer(batch):
    assert batch.parity
    assert batch.warehouse_total_cents == batch.lakehouse_total_cents


def test_the_simulations_are_deterministic():
    assert run_streaming()[0] == run_streaming()[0]
    assert run_batch() == run_batch()
