# ADR-0006 — A number never travels without its provenance

**Status:** accepted

## Context

The failure mode for a repo like this is not being wrong. It is being quoted. A
euro figure copied out of a generated report into a steering deck arrives there
without the sentence that said it was invented, and three meetings later it is a
budget line.

## Decision

Every surface that prints a euro figure states, in the same place, that the
figures are illustrative placeholders shaped like list pricing:

- `README.md` — an honesty statement above the fold.
- `reports/plan.md` — the placeholder notice before the first table.
- `reports/capacity-step.png` — a footer on the chart itself, because a chart is
  the artifact most likely to be screenshotted away from its context.
- `reports/simulation.md` — a section on what the measurements do and do not mean,
  as long as the results section.
- `config/cost_model.yaml` — a header comment explaining that the durable content
  is the shape and not the values.

Capability claims in `platforms.yaml` carry the same treatment for a different
reason: both platforms ship constantly, so every claim is dated by the commit that
made it and marked as needing re-checking against current vendor documentation.

## Consequences

The reports are more verbose than they would otherwise be, and the caveats
sometimes outweigh the findings in wordcount. That is the correct ratio for work
whose numbers are invented and whose *method* is the deliverable.

Anything added later that prints a figure must do the same. This is the one rule
in `AGENTS.md` with no exceptions.
