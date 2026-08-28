# FS-0003 — The capacity model

## Intent

Price Fabric as the pre-paid capacity it is, and Databricks as the meter it is
(ADR-0003).

## Acceptance criteria

- **THE SYSTEM SHALL NOT** expose a standalone monthly cost for a workload on
  Fabric. The only per-workload Fabric figure is its **marginal** cost against a
  named capacity.
- **WHEN** sizing a capacity **THE SYSTEM SHALL** select the smallest SKU on the
  configured ladder that clears the requirement, and **SHALL** report `None` when
  the requirement exceeds the largest rung.
- **THE SYSTEM SHALL** compute the requirement as the greater of the whole-estate
  allowance and the stricter interactive allowance, and **SHALL** report which one
  was binding.
- **WHEN** a workload is absorbed by existing capacity **THE SYSTEM SHALL** report
  its marginal cost as zero, and the plan **SHALL** state that zero is not free.
- **THE SYSTEM SHALL** total the capacity once, separately from workload rows.
- **THE SYSTEM SHALL** report amortised migration cost alongside run cost, and
  **SHALL** state that it is very nearly platform-independent.

## Covered by

`tests/test_capacity.py`
