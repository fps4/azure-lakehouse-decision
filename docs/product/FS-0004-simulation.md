# FS-0004 — The simulations

## Intent

Execute the two eliminations most likely to be waved through in a design review,
and be explicit about what a laptop can and cannot demonstrate (ADR-0001).

## Acceptance criteria

- **THE SYSTEM SHALL** generate its inputs deterministically, with no wall clock
  and no unseeded randomness.
- **WHEN** the streaming simulation runs **THE SYSTEM SHALL** send identical events
  — including late arrivals and redeliveries — through an ingestion-time shape and
  an event-time shape, and **SHALL** report each shape's error against a ground
  truth computed from distinct events by event time.
- **THE SYSTEM SHALL** report the two ingestion-time failures separately: the total
  inflated by redeliveries, and the per-window error caused by misplacement.
- **WHEN** the batch simulation runs **THE SYSTEM SHALL** kill a load between its
  two writes and report, for each shape, whether the aggregate still agrees with
  the fact beneath it.
- **THE SYSTEM SHALL** assert parity between the two correct shapes.
- **THE SYSTEM SHALL** publish an account of which measurements survive the DuckDB
  substitution and which do not, at least as prominent as the results.
- **IF** `deltalake` is absent **THEN THE SYSTEM SHALL** degrade and say so, never
  fail.

## Covered by

`tests/test_simulation.py`
