# ADR-0005 — The estate is data; the rules are code; nothing is both

**Status:** accepted

## Context

The fastest way to write this engine is to hard-code the estate into the rules —
`if workload_id == "STR_PAYMENTS"` and so on. It would be shorter and it would
produce the same register.

It would also be worthless, because the register would only describe one estate
and the reader would have no way to argue with it except by editing Python.

## Decision

No estate fact — a size, a rate, a threshold, a capability, a price — appears in
`src/`. All of it lives in `config/`:

| File | What it is |
|---|---|
| `estate.yaml` | The workloads. Facts about what exists. |
| `platforms.yaml` | What each platform can do. Facts, checkable against vendor docs. |
| `policy.yaml` | Thresholds and appetites. **Preferences, and arguable.** |
| `cost_model.yaml` | Prices and conversion factors. **Placeholders, and the most arguable.** |

Pydantic validates all four strictly. A typo in a workload kind or a missing
consumer profile fails loudly at load rather than silently becoming a default that
changes a platform decision.

## Consequences

Disagreement has somewhere to go. "Your CU-per-compute-hour factor for the
warehouse is too high" is not a debate — it is a one-line pull request against
`cost_model.yaml`, and `make decide` re-renders the plan with the consequence
attached. The same is true of every threshold in `policy.yaml`.

The separation also names the thing most likely to be wrong. The conversion
factors in `cost_model.yaml` — how much capacity a compute hour actually burns on
each engine — are the least defensible numbers in the repo and the ones that move
the answer most. Keeping them in one file, in one place, labelled, is the only
honest way to ship them.
