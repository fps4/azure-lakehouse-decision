.DEFAULT_GOAL := help
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install -U pip

.PHONY: install
install: $(BIN)/python ## Create the venv and editable-install with dev extras
	$(BIN)/pip install -e ".[dev]"

.PHONY: decide
decide: install ## Place every workload, size the capacity, write reports/
	$(BIN)/python -m azlake decide

.PHONY: explain
explain: install ## Explain one workload: make explain W=STR_PAYMENTS
	$(BIN)/python -m azlake explain $(or $(W),STR_PAYMENTS)

.PHONY: simulate
simulate: install ## Execute both platform shapes on local data
	$(BIN)/python -m azlake simulate

.PHONY: demo
demo: decide simulate ## The whole thing: the plan, the charts, both simulations
	@echo
	@echo "reports/plan.md              — the plan, with the reason in every row"
	@echo "reports/simulation.md        — R2 and R3, executed rather than asserted"
	@echo "reports/capacity-step.png    — the step function against the straight line"
	@echo "docs/platform-decision.md    — the one page to put on screen"

# ---- optional: real Delta tables, no Spark and no JVM ------------------------

.PHONY: delta
delta: $(BIN)/python ## Install the deltalake extra and re-run the simulation
	$(BIN)/pip install -e ".[dev,delta]"
	$(BIN)/python -m azlake simulate

.PHONY: test
test: install ## Run the test suite
	$(BIN)/pytest -q

.PHONY: lint
lint: install ## Lint
	$(BIN)/ruff check .

.PHONY: clean
clean: ## Remove generated data and reports
	rm -rf data/delta data/events reports/*.png reports/*.md
