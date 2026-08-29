# AGENTS.md — how this repo is built and worked

Spec-first and AI-assisted. Read this before changing anything.

## Working rules

1. **Specs lead code.** Every surface has a functional spec under `docs/product/`
   (FS-####) with EARS acceptance criteria, and a decision under
   `docs/design/decisions/` (ADR-####). Change the spec first, then the code.
2. **Honesty rule (ADR-0001, ADR-0006).** No production, scale or benchmark claims.
   No client names, no carried-over configuration. The README honesty statement is
   load-bearing — do not soften it.
3. **Local-first (ADR-0001).** The default path runs with no Azure subscription, no
   API key and no Docker. Do not add a required external dependency. `deltalake` is
   an extra and the simulation must degrade gracefully without it.
4. **Constraints eliminate; economics chooses (ADR-0002).** Never turn a constraint
   into a weight. New constraints are elimination rules in R1–R5, not terms in the
   cost function. `assess()` must never see a price.
5. **Never add `fabric_run_eur_month()` (ADR-0003).** A Fabric workload has no
   standalone price. The only per-workload Fabric figure is `marginal_eur` against
   a named capacity. A reviewer asking "what does this workload cost on Fabric?"
   is asking the question this repo exists to reject.
6. **Never charge platform overhead to a workload (ADR-0007).** It is not
   divisible — same reason as rule 5, one level up. It is reviewed at R9, once the
   whole allocation exists, and never priced inside R7.
7. **Branch on pricing shape, never on a vendor (ADR-0007).** There is one
   `metered_demand()` for every meter. A second one named after a product is how a
   comparison acquires a favourite. Adding a target is two YAML entries plus a
   `Platform` member; if it needs a new branch in `rules.py`, the abstraction is
   wrong and that is the thing to fix.
8. **Exactly one platform may declare `pricing: capacity`.** Two interacting
   ladders is a different allocation problem. `load_catalog()` raises; keep it
   raising rather than guessing.
9. **The estate is data (ADR-0005).** No estate fact — a size, a rate, a threshold,
   a capability, a price — is hard-coded. It goes in `config/`.
10. **Numbers carry their provenance (ADR-0006).** Any new figure states where it
   came from, in the file where it lives *and* in anything that prints it. Charts
   included — a chart is the artifact most likely to be screenshotted away from its
   caveats.
11. **Determinism.** No wall clock and no unseeded randomness in the catalog, the
   rules, or the generators. Two runs must differ only in timings.
12. **`assess()` stays one linear function.** Its ordering *is* the design.
   Splitting it into per-rule helpers would satisfy a linter and hide the argument.
13. **Capability claims are dated.** Anything in `config/platforms.yaml` is a claim
    about a fast-moving product. Adding one means adding the re-check reminder with
    it.
14. **A shut-out is a result.** A candidate that wins no workloads is reported as
    an outcome with its reason, never left as an empty column for the reader to
    infer. "Cheapest meter, but eliminated by a constraint" and "never cheapest"
    are different findings and must not read the same.

## Layout

- `docs/` — the one page, specs, ADRs (the design record)
- `config/` — estate, platforms, policy, cost model
- `src/azlake/` — `catalog.py`, `rules.py`, `capacity.py`, `econ.py`, `report.py`, `cli.py`
- `src/azlake/sim/` — `generate.py`, `batch.py` (R2), `streaming.py` (R3), `run.py`
- `tests/` — one test per rule, so a change to the rule set has to be deliberate
- `reports/` — generated; never edited by hand

## Definition of done for any change

- Matching spec updated; an ADR added if a real trade-off was made.
- `make lint`, `make test` and `make demo` green locally; CI green.
- `reports/plan.md` regenerated if the decisions moved, and any figure quoted in
  `README.md` or `docs/platform-decision.md` updated to match.
- No new required external dependency on the default path.
- If a euro figure was added anywhere, its provenance sentence went with it.
