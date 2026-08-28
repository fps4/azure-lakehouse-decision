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
6. **The estate is data (ADR-0005).** No estate fact — a size, a rate, a threshold,
   a capability, a price — is hard-coded. It goes in `config/`.
7. **Numbers carry their provenance (ADR-0006).** Any new figure states where it
   came from, in the file where it lives *and* in anything that prints it. Charts
   included — a chart is the artifact most likely to be screenshotted away from its
   caveats.
8. **Determinism.** No wall clock and no unseeded randomness in the catalog, the
   rules, or the generators. Two runs must differ only in timings.
9. **`assess()` stays one linear function.** Its ordering *is* the design.
   Splitting it into per-rule helpers would satisfy a linter and hide the argument.
10. **Capability claims are dated.** Anything in `config/platforms.yaml` is a claim
    about a fast-moving product. Adding one means adding the re-check reminder with
    it.

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
