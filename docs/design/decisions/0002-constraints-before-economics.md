# ADR-0002 — Constraints eliminate; economics chooses

**Status:** accepted

## Context

A platform comparison naturally wants to be a weighted score. Give each platform
points for T-SQL support, for streaming semantics, for ML, for price; weight the
columns; take the winner. Every vendor comparison deck works this way.

It is the wrong shape, and the reason is not aesthetic. A weighted score lets a
sufficiently large price advantage purchase its way past a residency rule, a
data-classification clearance or an exactly-once guarantee. In a spreadsheet that
looks like a trade-off. In production it is an incident, and in a regulated estate
it is a finding.

## Decision

The rule set is split, and the split is enforced by the code's structure rather
than by convention:

- **R1–R5 eliminate.** They return a platform-to-reason mapping and never a number.
  Residency and clearance, T-SQL surface, streaming semantics, sub-second
  telemetry, ML lifecycle.
- **R7 chooses**, and only among what survived.

`assess()` cannot see a price. `build_plan()` cannot reach a workload whose
platform was eliminated. A workload with no survivor is assigned
`STAY_ON_SYNAPSE` rather than being given the cheapest option anyway.

`tests/test_rules.py::test_constraints_are_never_overruled_by_economics` asserts
the invariant across the whole estate.

## Consequences

The plan can produce an answer nobody wants — `STR_PAYMENTS` is eliminated from
Fabric by its streaming semantics and from Databricks by its data clearance, and
therefore stays on Synapse. That is not a bug in the engine. It is the engine
declining to pretend, and it is the most useful row in the register: it says
precisely which single constraint has to change for the workload to move.

The cost of the decision is that a constraint cannot be traded, only changed. If
the estate would in fact accept a rewrite, the switch is
`policy.tsql.eliminate_when_surface_unsupported: false` and the cost model prices
it. Flipping a policy flag is a decision someone makes on purpose; a weight
quietly outvoting a constraint is not.
