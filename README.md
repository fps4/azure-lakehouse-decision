# azure-lakehouse-decision

**A Synapse estate has to go somewhere.** Microsoft Fabric, Databricks-on-Azure or
Snowflake-on-Azure — with the decision made **explicit, priced against Fabric's
capacity model, and runnable**.

Most platform comparisons are a capability matrix with forty rows and no numbers.
This one comes with the argument attached: a catalog of 20 workloads across a
Synapse estate, an ordered rule set where constraints eliminate and economics
chooses, a cost model that takes the F-SKU ladder seriously enough that a
workload's platform depends on what else is on the platform, and two local
simulations that **execute** the two eliminations most likely to be nodded through
in a design review.

```
   THE SYNAPSE ESTATE            THE LADDER                  WHERE IT LANDS
 dedicated SQL pool          R1  residency & clearance    ┌▶ FABRIC
 serverless views            R2  T-SQL surface            │  one pre-paid capacity
 Spark notebooks       ────▶ R3  streaming semantics    ──┤  marginal cost €0 …
 pipelines                   R4  sub-second telemetry     │  … then a whole rung
 streams (Event Hub)         R5  ML lifecycle             │
                             ─────────────────────────    ├▶ DATABRICKS · SNOWFLAKE
                             R6  Direct Lake premium      │  metered, per DBU
                             R7  economics, capacity-aware│  or per credit
                             R8  step-boundary review     │  straight lines
                             R9  platform portfolio       │
                             R10 locality (advisory)      └▶ STAYS ON SYNAPSE
                                                             nothing survived
```

**→ Start with [`docs/platform-decision.md`](docs/platform-decision.md).** That is
the page to put on a screen. Everything else exists to defend it.

## Honesty statement

This is a **decision procedure with a working engine behind it**, authored
**AI-assisted** (agentic workflow; the specs under `docs/` are the design record
and lead the code). What runs is real: the catalog, the rules, the capacity model,
both simulations, the reports — `make demo` produces all of it on a laptop in about
a minute.

What is **not** real, and is labelled as such everywhere it appears:

- **No Azure subscription, no Fabric capacity, no Databricks workspace and no
  Snowflake account are involved.** DuckDB stands in for all of them. Fabric in
  particular *cannot* run locally — there is no emulator — so it is modelled, not
  executed. The simulation report is explicit about which of its measurements
  survive that substitution and which do not, and that section is as long as the
  results ([ADR-0001](docs/design/decisions/0001-local-first-runtime.md)).
- **The euro figures are illustrative placeholders shaped like list pricing**, not
  quotes and not a rate card. They live in one YAML file precisely so they can be
  replaced ([ADR-0006](docs/design/decisions/0006-numbers-carry-provenance.md)).
- **The conversion factors are the weakest numbers here** — how much capacity a
  compute hour actually burns on each engine, and how a CU compares to a DBU or a
  credit. They move the answer more than anything else and they are the first
  thing to replace with measured ones.
- **The 20-workload estate is invented.** Shaped like a mid-size Azure estate that
  grew through Synapse between 2020 and 2024; it is not one.
- **All three platforms ship constantly.** Every capability claim in
  `config/platforms.yaml` is dated by its commit and must be re-checked against
  current Microsoft, Databricks and Snowflake documentation before it decides a
  budget. Two Snowflake claims are close calls and are marked as such in the file.
- **Nothing here is a benchmark.** No throughput, no latency, no capacity sizing
  under real concurrency. Those decide what a real programme costs and none of them
  can be inferred from anything in this repo.

The durable artifact is the **decision procedure**, not the euro figures and
certainly not the capability matrix.

## Why it exists

**Because a Fabric workload has no price.** Databricks and Snowflake are metered —
a workload's cost is a property of the workload, true on its own. Fabric is a
pre-paid capacity: one F-SKU carries the estate, and one more workload costs
**nothing** until the capacity saturates and then costs **the price of the next
rung**. A per-workload price table cannot represent that, so every comparison built
as a price table is answering a question nobody asked
([ADR-0003](docs/design/decisions/0003-capacity-is-not-a-price-list.md)).

**Because a platform costs money to operate, not just to consume.** With one meter
in the comparison that never mattered — the estate was always going to run it. With
two, the contract, landing zone, identity integration and the people who know it
become a decision variable, and that cost is not divisible by workload either. A
meter can win five workloads and still lose the estate
([ADR-0007](docs/design/decisions/0007-a-platform-costs-something-to-open.md)).

**Because a matrix cannot be challenged and an engine can.** Disagreeing with a
cell on a slide gets nowhere. Here, disagreement is a pull request against
`config/policy.yaml` or `config/cost_model.yaml`, and the plan re-renders with the
consequence attached.

## Quickstart

```bash
make demo          # the plan, the charts, and both simulations
```

Or step by step:

```bash
make install       # venv + editable install
make decide        # place all 20 workloads, size the capacity, write reports/
make explain W=STR_PAYMENTS
make simulate      # execute both platform shapes on local data
make test
```

Requires Python 3.11+. No Azure subscription, no API key, no Docker.

Real Delta tables — transaction log and all, no Spark and no JVM — are an optional
extra so the default path stays dependency-light:

```bash
make delta         # install `deltalake`, then materialise the streaming sink
```

## What `make decide` prints

```
ESTATE: 20 workloads · target region westeurope · 3 candidate platforms

WORKLOAD               KIND             PLATFORM    SURFACE                CU-H/MO     €/MO  WHY
----------------------------------------------------------------------------------------------
FCT_GL_POSTING         dedicated_sql    Fabric      warehouse                2,207        0  [R1-R5] Only surviving platform
NB_TELEMETRY_ROLLUP    spark_notebook   Fabric      lakehouse                5,227        0  [R7] Absorbed by the F32 capacity...
NB_SALES_CURATION      spark_notebook   Databricks  jobs_compute             3,040      460  [R7] Would push the capacity to F64...
STR_DEVICE_TELEMETRY   stream           Fabric      eventhouse               2,663        0  [R1-R5] Only surviving platform
STR_PAYMENTS           stream           Synapse     synapse                    719        0  [R1-R5] Every candidate was eliminated
STR_INVENTORY_MOVE     stream           Databricks  structured_streaming       852      205  [R1-R5] Only surviving platform
...

MIX   FABRIC: 15  DATABRICKS: 4  SYNAPSE: 1
CAP   F32 · 24.0 CU sustained of 32 (75% used) · sized by the total allowance at 32.0 CU required
RUN   €8,362/month  (capacity €4,444 · metered Databricks €1,618 · platform overhead €2,300 across 2 platforms)
MOVE  €19,833/month amortised over 24 months — 70% of the bill, and almost identical on every target
R8    F16 is unreachable: the workloads pinned to Fabric by R1–R5 alone require 19.6 CU
      (interactive-bound). The capacity floor is set by constraints, not by the batch workloads
      R7 added — so evicting batch cannot shrink it
NONE  Snowflake won nothing: cheapest meter on 5 workload(s), barred by a constraint on 4 of them
HELD  STR_PAYMENTS — no target survives its constraints
```

`make explain W=STR_PAYMENTS` prints one workload in full: every elimination named,
all three platforms' demand, and the marginal cost that actually decided it.

## The six things to look at

1. **The one page** — [`docs/platform-decision.md`](docs/platform-decision.md).
   The ladder, the capacity argument, and how to disagree with it.
2. **The empty column** — Snowflake wins nothing, and is **the cheapest meter on
   five of the twenty workloads**. Four of those are eliminated by R2 before a price
   is read, because they are written in T-SQL; the fifth is absorbed by capacity
   already paid for. *The platform prices best exactly where it is not allowed to
   compete.* A capability matrix cannot reach that — it has no prices. A price table
   cannot either — it has no constraints.
3. **The rules, in order** — [`src/azlake/rules.py`](src/azlake/rules.py). R1–R5
   cannot see a price; R7 is the first rule that can. The code is arranged so that
   economics *cannot* overrule a constraint, and a test asserts it across the
   estate.
4. **R9, and what it costs to open a platform** — set
   `tsql.eliminate_when_surface_unsupported: false` and re-run. Snowflake takes
   `FCT_GL_POSTING` at €647/month against Databricks' €796 — and R9 hands it back,
   because €149/month of saving does not cover €1,200/month of platform overhead.
   **Winning workloads and winning an estate are different things.**
5. **The capacity** — [`src/azlake/capacity.py`](src/azlake/capacity.py). The
   ladder, and the two allowances that size it. There is deliberately no
   `fabric_run_eur_month()` anywhere in this repo.
6. **The workload with no home** — `STR_PAYMENTS` in
   [`reports/plan.md`](reports/plan.md). Eliminated from Fabric and Snowflake by its
   streaming semantics and clearance, and from Databricks by its data clearance. A
   third candidate did not rescue it. It is the most useful row in the register
   because it names the single fact that has to change — and with Synapse ending,
   "leave it where it is" now has an expiry date.

**And two things executed rather than asserted**, in
[`reports/simulation.md`](reports/simulation.md): the same payment stream through
both streaming shapes — the ingestion-time engine finishes **3.49% out per window**
and over-counts by every redelivery, while the event-time shape restates 245
windows and lands exactly on the truth; and a load killed between its two writes,
which rolls back clean with a multi-table transaction and leaves **893 customers**
whose aggregate disagrees with the fact beneath it without one.

## Layout

| Path | What it is |
|---|---|
| `docs/platform-decision.md` | **The one page.** |
| `docs/product/` | Functional specs (FS-####) — what each surface must do |
| `docs/design/decisions/` | ADRs — the trade-offs, written down |
| `config/estate.yaml` | The 20 workloads. Facts. |
| `config/platforms.yaml` | What each platform can do, and how it is priced. Dated claims. |
| `config/policy.yaml` | Thresholds and appetites. **Arguable.** |
| `config/cost_model.yaml` | Prices and conversion factors. **Placeholders.** |
| `src/azlake/` | Catalog, rules, capacity, economics, reporting, CLI |
| `src/azlake/sim/` | The two local simulations |
| `reports/` | Generated: the plan, the simulation, the charts |

## License

MIT — see [`LICENSE`](LICENSE).
