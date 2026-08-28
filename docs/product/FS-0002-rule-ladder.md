# FS-0002 — The rule ladder

## Intent

Assign every workload a destination, in an order where constraints eliminate and
economics chooses (ADR-0002).

    R1  residency & clearance
    R2  T-SQL surface
    R3  streaming semantics
    R4  sub-second telemetry
    R5  ML lifecycle
    R6  semantics premium (Direct Lake)
    R7  economics, capacity-aware
    R8  step-boundary review
    R9  locality (advisory)

## Acceptance criteria

- **THE SYSTEM SHALL** evaluate R1–R5 with no access to any price.
- **IF** a platform is eliminated for a workload, **THEN THE SYSTEM SHALL NOT**
  place that workload on that platform under any economic condition.
- **IF** every candidate is eliminated, **THEN THE SYSTEM SHALL** assign
  `STAY_ON_SYNAPSE` and retain every elimination reason.
- **WHEN** a workload's consumer is a Direct Lake semantic model, **THE SYSTEM
  SHALL** allow a Fabric placement up to `semantics.max_premium_ratio` times the
  metered alternative, and no further.
- **THE SYSTEM SHALL** produce an identical plan on repeated runs with identical
  configuration.
- **THE SYSTEM SHALL** record, per workload, the rule that decided it and a reason
  that names the specific fact responsible.

## Covered by

`tests/test_rules.py` — one test per rule, plus the cross-estate invariant that
economics never overrules a constraint.
