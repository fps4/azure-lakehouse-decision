"""The local simulation.

Two claims in the rule set are the kind that get waved through in a design review
because everybody nods at them. This package executes both instead:

* **R2** — a transactional T-SQL surface is not a stylistic preference. `batch.py`
  fails a load halfway through, twice, and shows what each shape leaves behind.
* **R3** — an ingestion-time engine is not a cheaper event-time engine.
  `streaming.py` sends the same events, late and duplicated, down both shapes and
  measures how far apart the answers end up.

Nothing here runs on Azure. DuckDB stands in for both engines, so what survives
the substitution is *semantics* and what does not is *performance* — see ADR-0001,
and the honest account in `reports/simulation.md`.
"""
