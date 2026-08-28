# Changelog

## 0.1.0

First cut.

- A 20-workload Synapse estate as validated configuration, with the platforms,
  policy and cost model beside it (ADR-0005).
- The rule ladder R1–R9: residency and clearance, T-SQL surface, streaming
  semantics, sub-second telemetry, ML lifecycle, the Direct Lake premium,
  capacity-aware economics, the step-boundary review, and locality as advice.
  Constraints eliminate; economics chooses (ADR-0002).
- Fabric priced as a pre-paid capacity on an F-SKU ladder rather than as a price
  list, so a workload's marginal cost depends on what else is on the capacity
  (ADR-0003). Two sizing allowances, whole-estate and interactive, with the
  binding one reported.
- Two local simulations that execute rather than assert: the ingestion-time versus
  event-time streaming shapes (R3), and transactional versus idempotent batch
  loading under an injected failure (R2).
- Generated reports: the plan with the reason in every row, the simulation with an
  account of what a laptop can and cannot demonstrate, and two charts.
