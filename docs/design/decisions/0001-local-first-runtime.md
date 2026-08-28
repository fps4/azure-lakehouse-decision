# ADR-0001 — The default path runs on a laptop

**Status:** accepted

## Context

The subject of this repo is two cloud platforms. The obvious way to demonstrate a
claim about them is to deploy to them. Fabric in particular cannot be run locally
at all: OneLake, Direct Lake, Eventstream and Eventhouse are cloud-only, there is
no emulator, and a capacity is a purchase rather than a container.

So the choice is between a repo that costs money to run and is therefore never run
by the person reading it, and a repo that runs in a minute and is honest about
what it is standing in for.

## Decision

`make demo` runs with **no Azure subscription, no Fabric capacity, no Databricks
workspace, no API key and no Docker**. DuckDB stands in for both engines. The
`deltalake` extra is optional and the simulation degrades gracefully without it.

Every generated report carries an explicit account of which measurements survive
the substitution and which do not, and that account is as prominent as the results.

## Consequences

**What this buys.** The argument can be checked by anyone in under a minute, and
disagreement becomes a pull request against `config/` rather than a difference of
opinion. That is the entire value proposition: the numbers are wrong on purpose
and easy to replace.

**What it costs, stated plainly.** Nothing here measures throughput, latency, cost
per query, capacity sizing under real concurrency, or any operational property of
either platform. Those are the things that decide what a real programme costs and
none of them can be inferred from anything in this repo.

What *does* survive is semantics — ingestion time versus event time, deduplication,
watermarks, transactional maintenance versus idempotent replacement. Those are
properties of the design, not of the runtime, and they are what the rule set turns
on. See `reports/simulation.md`, which says this again where the numbers are.

**Rejected:** a Terraform/Bicep deployment on the default path. It would make the
repo unrunnable for its actual readers and would not make the cost model any less
of a placeholder.
