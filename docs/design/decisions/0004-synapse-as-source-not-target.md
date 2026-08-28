# ADR-0004 — Synapse is the source, never a target

**Status:** accepted

## Context

Synapse Analytics is where a great many Azure estates currently are. It is not
where Microsoft's go-forward investment points — Fabric is the successor story,
and new build lands there or on Databricks.

A repo could therefore treat Synapse three ways: as a target worth choosing, as a
platform to benchmark against the other two, or as the estate that has to move.

## Decision

Synapse appears only as the **source estate** — a catalog of workloads in
`config/estate.yaml` with the properties that decide where each can go: a T-SQL
surface, a consumer, a latency class, a governance classification.

`Platform.STAY_ON_SYNAPSE` exists but is not in `CANDIDATES`. It is not a choice
the engine can make on economic grounds; it is what is left when R1–R5 eliminate
everything, and it always carries the reasons.

## Consequences

**Why this framing rather than a three-way comparison.** A Fabric-versus-Databricks
feature table is a commodity — there are hundreds, they are mostly accurate, and
none of them helps anyone decide anything, because the decision is never made per
feature. It is made per workload, against an estate that already exists, with
constraints that were set years ago by people who have left.

Treating Synapse as the source makes the repo answer the question estates actually
have ("where does *this* go, and what does it cost") rather than the question
vendors answer ("which platform is better").

**The honest limitation.** Nothing here evaluates whether the estate should move at
all. Staying on Synapse and doing nothing is a real option with a real cost, and it
is out of scope. This repo starts one step after that decision.
