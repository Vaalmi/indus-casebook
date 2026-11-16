# The one check command is `make check` (docs/PROCESS.md). It calls no model and no network.
.PHONY: setup check

PLAYWRIGHT_FLAGS ?=
MONEY_PACKAGES = src/casebook/model src/casebook/replay src/casebook/keys src/casebook/rules

setup:
	uv sync --frozen
	uv run playwright install $(PLAYWRIGHT_FLAGS) chromium
	git config core.hooksPath .githooks

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright
	uv run lint-imports
	uv run python tools/check_no_float.py $(MONEY_PACKAGES)
	uv run python tools/check_licences.py
	uv run pytest
