# ADR-0003 — A Fabric workload has no standalone price

**Status:** accepted

## Context

The natural way to compare two platforms is a table: one row per workload, one
column per platform, a euro figure in each cell. Pick the cheaper cell.

That table cannot be built for Fabric, and the reason is structural rather than a
data-gathering problem. Databricks is metered: a workload's cost is a property of
the workload, true on its own. Fabric is a **pre-paid capacity**: the estate buys
an F-SKU and every workload consumes CU-seconds from one shared pool. The marginal
cost of one more workload is **zero** while the capacity absorbs it, and **the
price of the next rung** when it does not.

So the same workload costs €0 or €2,756 a month depending on what else is on the
capacity. A per-workload price column would have to pick one, and either choice is
a lie in one direction.

## Decision

The engine models the capacity, not a price list.

- `econ.databricks_run_eur_month()` exists. There is deliberately **no**
  `fabric_run_eur_month()`.
- `capacity.size_capacity()` takes a *set* of workloads and returns a sized rung.
- `capacity.marginal_eur()` is the only per-workload Fabric number, and it is a
  property of the workload *and the capacity it joined*.
- R7 is therefore an allocation, not a sort. It places workloads one at a time
  against a capacity that changes underneath it, biggest metered bill first, so
  the workload with most to save gets first claim on free headroom.
- The plan totals the capacity **once**, separately, so a `€0` in a workload row
  cannot be read as an absence.

## Consequences

Three findings fall out that a price table cannot produce, and they are the reason
the repo exists:

1. **Unused headroom is the cheapest compute in the estate**, and the only way to
   use it is to put something on it. Several batch workloads land on Fabric for a
   marginal €0 against a real metered alternative.
2. **The workload that forces a rung pays for the whole rung.** Two notebooks are
   on Databricks solely because they would have stepped F32 to F64.
3. **The plan finishes sitting against a boundary**, because R7 fills until the
   next workload steps it. That is correct behaviour and it is why R8 exists —
   and why the naive version of `test_adding_a_workload_is_free_until_it_is_not`
   fails when measured from the finished plan.

The cost: the engine is order-dependent, so the ordering had to be chosen and
justified rather than falling out of a sort. It is deterministic and tested, but
it is a greedy heuristic and not an optimum. A different order would produce a
different — possibly better — plan. R8 is the check against the worst of that,
and it is not a proof.
