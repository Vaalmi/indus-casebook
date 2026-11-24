# The one check command is `make check` (docs/PROCESS.md). It calls no model and no network.
.PHONY: setup check

PLAYWRIGHT_FLAGS ?=
# Four workers, each test file on one of them so a file's fixtures build once: the suite took 16 minutes on the
# owner's Mac this way, 22 spreading single tests, 19 on all 18 cores and 43 in one process (24 November 2026). A
# GitHub runner has four cores.
PYTEST_WORKERS ?= 4
MONEY_PACKAGES = src/casebook/model src/casebook/replay src/casebook/keys src/casebook/rules src/casebook/tax
# Tax-Calculator computes in float; its one boundary converts every figure to Decimal as it leaves.
FLOAT_BOUNDARY = src/casebook/tax/crosscheck.py

setup:
	uv sync --frozen
	uv run playwright install $(PLAYWRIGHT_FLAGS) chromium
	git config core.hooksPath .githooks

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run lint-imports
	uv run python tools/check_no_float.py $(MONEY_PACKAGES) --except $(FLOAT_BOUNDARY)
	uv run python tools/check_licences.py
	uv run pytest -n $(PYTEST_WORKERS) --dist loadscope
