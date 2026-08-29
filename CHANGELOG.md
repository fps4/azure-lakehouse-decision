# Changelog

## 0.2.0

**Snowflake on Azure added as a third target**, and the engine generalised from a
two-platform comparison to N platforms of two *pricing shapes*.

- `platforms.yaml` restructured around a platform map with a declared `pricing`
  field, `capacity` or `metered`. `econ.py`, `rules.py` and `report.py` branch on
  the shape and never on a vendor: one `metered_demand()` serves every meter, and
  adding a target is two YAML entries plus a `Platform` member (ADR-0007).
  `load_catalog()` raises if more than one platform claims to be a capacity, if a
  metered platform has no meter, or if a candidate has no overhead.
- Snowflake capability facts as dated claims, with the two close calls marked as
  such: the exactly-once reading of Snowpipe Streaming, and Direct Lake over
  Snowflake-managed Iceberg. Its T-SQL gap is documented as a *dialect* gap and
  deliberately distinguished from Databricks' *atomicity* gap, which is the one
  the batch simulation executes.
- **R9 · platform portfolio review** — a platform costs money to operate, not
  merely to consume, and that cost is not divisible by workload. R7 places one
  workload at a time and cannot see it. R9 asks, once the allocation exists,
  whether every platform opened on economics alone covered its own overhead, and
  closes the ones that did not. A platform R1–R5 pinned a workload to is not
  reviewable. Locality moves to R10.
- R7 now compares every surviving meter and records what the rejected ones would
  have cost. R8 re-homes each evicted workload to its own cheapest surviving meter
  rather than to a default second choice.
- A candidate that wins nothing is reported as a result, distinguishing "never the
  cheapest meter" from "cheapest on workloads a constraint eliminated it from".
  In this estate Snowflake is the latter: cheapest meter on five of twenty
  workloads, eliminated by R2 from four of them.
- The plan, the console summary, `explain` and both charts carry all three
  platforms. Reports regenerated.

Behaviour note: the default plan is unchanged — same placements, same F32, same
€8,362/month. The third candidate wins nothing, and the report now says why.


## 0.1.0

First cut.

- A 20-workload Synapse estate as validated configuration, with the platforms,
  policy and cost model beside it (ADR-0005).
- The rule ladder R1–R9 (as it then was): residency and clearance, T-SQL surface,
  streaming semantics, sub-second telemetry, ML lifecycle, the Direct Lake
  premium, capacity-aware economics, the step-boundary review, and locality as
  advice. Constraints eliminate; economics chooses (ADR-0002).
- Fabric priced as a pre-paid capacity on an F-SKU ladder rather than as a price
  list, so a workload's marginal cost depends on what else is on the capacity
  (ADR-0003). Two sizing allowances, whole-estate and interactive, with the
  binding one reported.
- Two local simulations that execute rather than assert: the ingestion-time versus
  event-time streaming shapes (R3), and transactional versus idempotent batch
  loading under an injected failure (R2).
- Generated reports: the plan with the reason in every row, the simulation with an
  account of what a laptop can and cannot demonstrate, and two charts.
