# FS-0003 — The capacity model

## Intent

Price Fabric as the pre-paid capacity it is, and every other candidate as the
meter it is (ADR-0003), branching on a declared pricing shape rather than on a
vendor name (ADR-0007).

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
- **THE SYSTEM SHALL** describe every metered platform with one model and one
  demand function, so that adding a meter is a configuration change.
- **THE SYSTEM SHALL** charge the platform overhead of each platform operated
  exactly once, independently of how many workloads it carries.
- **THE SYSTEM SHALL NOT** charge a platform's overhead to any individual
  workload — it is not divisible, which is why it is reviewed at R9 rather than
  priced at R7 (ADR-0007).
- **IF** more than one platform declares `pricing: capacity`, **THEN THE SYSTEM
  SHALL** raise at load time rather than model two interacting ladders.

## Covered by

`tests/test_capacity.py`
