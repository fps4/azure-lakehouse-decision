# ADR-0007 — A third platform, and the cost of opening one

**Status:** accepted
**Supersedes:** nothing. Extends [ADR-0003](0003-capacity-is-not-a-price-list.md).

## Context

The repo began as Fabric versus Databricks: one capacity against one meter. Adding
**Snowflake on Azure** as a third target changes two things, and only one of them
is obvious.

The obvious one is arithmetic. Three candidates instead of two, one more column in
every table, one more line on the chart. That is bookkeeping.

The second is structural, and it is the reason this ADR exists. With one meter, the
economics stage answers *"capacity or meter?"* — and the fixed cost of running the
meter is not a variable, because the estate was always going to run it. With two
meters, the estate might run **one, or both, or neither**, and the fixed cost of
operating a platform — contract, landing zone, identity integration, network path,
and the people who know it — becomes a decision variable for the first time.

That cost has the same awkward property as a capacity rung: **it is not divisible
by workload.** A meter that wins five workloads by €200/month each has won
€1,000/month of consumption and, if standing the platform up costs €1,200/month,
has lost the estate €200/month. R7 places one workload at a time and cannot see
this, in exactly the way a per-workload price table cannot see a capacity rung.
It is the same blind spot, one level up.

## Decision

**1. The engine reasons about pricing *shapes*, not vendors.**

`platforms.yaml` gains a `pricing` field, `capacity` or `metered`. Everything in
`econ.py`, `rules.py` and `report.py` branches on that field. There is one
`metered_demand()` for every meter, not one function per vendor, and adding a
fourth target is an entry in two YAML files plus a member of `Platform` — not a new
branch in the rules. A per-vendor code path is how a comparison quietly acquires a
favourite.

Exactly one platform may be `capacity`, and `load_catalog()` raises otherwise. Two
interacting ladders — where filling one does nothing to empty the other — is a
genuinely different allocation problem, and pretending the current code solves it
would be worse than refusing it.

**2. Platform overhead is reviewed after allocation, as R9, not priced during it.**

The alternative was to charge the first workload onto a platform its full entry
fee inside R7. That is wrong in a way worth recording: it makes the answer depend
on the order workloads are considered, and it penalises a platform that five
workloads would jointly justify because the first one alone cannot. Non-additive
costs cannot be charged to an individual — that is what non-additive means, and it
is the same reason `fabric_run_eur_month()` does not exist.

So R7 stays as it was, blind to overhead, and **R9 asks the question once the whole
allocation is visible**: for each platform opened on economics alone, is its metered
cost plus its overhead more than re-homing everything on it to the next-best option
that is already open? If so, close it.

**3. A platform that R1–R5 pinned a workload to is not reviewable.**

If some workload survives nowhere else, that platform's overhead is not a choice,
and free workloads may join it for the price of their own consumption. Constraints
still outrank economics, including when the economics is about a platform rather
than a workload (ADR-0002).

**4. A shut-out is a result, and is reported as one.**

In the default estate Snowflake wins nothing. That is not an absence to be left to
inference — the plan states it, and states which of the two ways it happened: never
the cheapest meter, or cheapest on workloads a constraint took away.

## Consequences

**What this buys.** The estate's actual finding is one no capability matrix could
produce and no price table could either: *Snowflake is the cheapest meter for the
dedicated SQL pool, and R2 eliminates it from four of those five workloads because
they are written in T-SQL.* The platform prices best exactly where it is not allowed
to compete. Reaching that needs constraints and prices in the same sentence, which
is the whole argument for having an engine rather than a slide.

**What it costs.** R9 does not fire on the default run, because nothing opens
Snowflake and an unopened platform has nothing to review. It is one documented flag
away, though, and the flag is one a real estate would actually consider:

```bash
# policy.yaml → tsql.eliminate_when_surface_unsupported: false
# "we accept a rewrite of the finance warehouse; price it, do not eliminate it"
make decide
```

With R2 relaxed, R7 gives `FCT_GL_POSTING` to Snowflake — it is the cheapest meter
for it, €647/month against Databricks' €796. R9 then closes the platform again:
€647 of consumption plus €1,200/month of overhead, against €796/month to re-home it
to a platform already open. **Net €1,051/month to not have a third vendor**, for a
workload that genuinely was cheaper on it. That is the rule earning its place, and
it is reachable from the shipped configuration rather than only from a test.

Both branches are also covered directly —
`test_r9_closes_a_platform_that_cannot_pay_its_own_overhead` and its mirror — on
catalogs built to force each outcome, because relying on a flag flip for coverage
would make the tests hostage to the estate's numbers.

**What is still not modelled.** R9 re-homes to platforms already open and will not
close one platform in order to open another — that trades one overhead for another
and is not a saving. It also does not consider closing *two* platforms together.
Both are real cases; neither arises in this estate, and guessing at them without a
case to check against is how an engine acquires untested cleverness.

**The Snowflake capability claims are the usual dated claims** (ADR-0006), and two
of them are close calls that are marked as such in `platforms.yaml`: the
exactly-once reading of Snowpipe Streaming, and Direct Lake over Snowflake-managed
Iceberg, which is the claim in this repo most likely to age.
