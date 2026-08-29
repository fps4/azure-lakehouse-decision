# FS-0001 — The estate and the platforms, as data

## Intent

Everything the engine reasons about is loadable, validated configuration. No
estate fact lives in code (ADR-0005).

## Acceptance criteria

- **WHEN** `load_catalog()` is called **THE SYSTEM SHALL** load and strictly
  validate `estate.yaml`, `platforms.yaml`, `policy.yaml` and `cost_model.yaml`.
- **IF** a workload declares a `kind` for which any candidate platform has no
  surface, **THEN THE SYSTEM SHALL** raise at load time rather than default.
- **IF** a candidate platform has no configuration, no meter behind a `metered`
  declaration, or no platform overhead, **THEN THE SYSTEM SHALL** raise at load
  time. A metered platform with no meter would cost nothing and win everything.
- **IF** two workloads share an `id`, **THEN THE SYSTEM SHALL** raise.
- **WHERE** a field is a preference rather than an estate fact, **THE SYSTEM
  SHALL** locate it in `policy.yaml` or `cost_model.yaml`, never in `estate.yaml`.
- **THE SYSTEM SHALL** treat every capability in `platforms.yaml` as a dated claim
  requiring re-verification against vendor documentation (ADR-0006).
- **THE SYSTEM SHALL** hold the platform list itself as data: adding a target is an
  entry in `platforms.yaml` and `cost_model.yaml` plus a member of `Platform`, and
  **SHALL NOT** require a vendor-specific branch in the rules (ADR-0007).

## Covered by

`tests/test_catalog.py`
