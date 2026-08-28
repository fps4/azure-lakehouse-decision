# Product intent

## The question this answers

An Azure estate grew through Synapse Analytics. It now has a dedicated SQL pool
carrying finance and sales, serverless views over the raw zone, Spark notebooks
doing the transformation, pipelines orchestrating it, and streams that arrived
later and never quite fitted.

Microsoft's go-forward story is Fabric. Databricks is on Azure and is what half the
estate's engineers already know. Someone has to decide where each workload goes.

**The question is not "Fabric or Databricks".** It is "where does *this* workload
go, what does it cost, and what happens to the ones that fit neither".

## Why the usual artifact does not answer it

The usual artifact is a capability matrix. Forty rows, two columns, ticks and
crosses. It is mostly accurate and it decides nothing, for three reasons:

1. **Most rows do not eliminate anything.** Four or five do. The rest are noise
   that makes the comparison look thorough.
2. **It has no prices**, and where it does, it prices per workload — which cannot
   be done for a capacity platform at all (ADR-0003).
3. **It cannot be argued with.** Disagreeing with a cell on a slide gets nowhere.

## What this is instead

A decision procedure with the argument attached:

- a catalog of the estate as data;
- an ordered rule set where constraints eliminate and economics chooses;
- a cost model that takes Fabric's capacity ladder seriously, so the answer for a
  workload depends on what else is on the capacity;
- two simulations that execute the two eliminations most likely to be waved
  through; and
- a plan that puts the reason in the row, including what the rejected option would
  have cost.

Disagreement is a pull request against `config/`, and the plan re-renders with the
consequence.

## What it is not

- Not a benchmark. Nothing here measures either platform's performance (ADR-0001).
- Not a pricing tool. The euro figures are placeholders (ADR-0006).
- Not a migration plan. It answers *which target*, not *how to get there safely* —
  waves, parity gates, cutover and rollback are a different problem.
- Not an argument that the estate should move at all (ADR-0004).

## Success criterion

A reader who disagrees with the answer can find the exact line in `config/` that
produced it, change it, and see what happens. If they cannot, this has failed
regardless of whether the answer was right.
