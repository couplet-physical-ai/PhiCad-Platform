SHELL := /usr/bin/env bash

PYTHON ?= python3
VERSION ?= 0.1.0-dev.1
DIST_DIR ?= release/dist

.PHONY: ci-install lint test unit test-unit test-mcp install-test docs-strict \
	validate-lock secret-scan shellcheck package package-verify inventory release-test

# Install only repository-declared dependencies plus the small set of CI tools.  This
# deliberately does not use credentials, private indexes, or organization secrets.
ci-install:
	@$(PYTHON) -m pip install --disable-pip-version-check --upgrade pip
	@if [ -f pyproject.toml ] || [ -f setup.py ] || [ -f setup.cfg ]; then \
		$(PYTHON) -m pip install --disable-pip-version-check -e .; \
	else \
		echo 'No Python project metadata found; skipping editable install'; \
	fi
	@$(PYTHON) -m pip install --disable-pip-version-check pytest ruff

lint:
	@if command -v ruff >/dev/null 2>&1 || $(PYTHON) -m ruff --version >/dev/null 2>&1; then \
		$(PYTHON) -m ruff check . 2>/dev/null || ruff check .; \
	else \
		echo 'ruff is not installed; running Python bytecode compilation instead'; \
		$(PYTHON) -m compileall -q .; \
	fi

test: unit
unit test-unit:
	@$(PYTHON) release/run_tests.py unit

test-mcp:
	@$(PYTHON) release/run_tests.py mcp

install-test:
	@$(PYTHON) release/install_test.py

docs-strict:
	@$(PYTHON) release/docs_check.py

validate-lock:
	@$(PYTHON) release/validate_versions.py --repo-root .

secret-scan:
	@$(PYTHON) release/secret_scan.py --root .

shellcheck:
	@files="$$(find . -type f -name '*.sh' -not -path './.git/*' -not -path './release/dist/*' -print)"; \
	if [ -z "$$files" ]; then \
		echo 'No shell scripts found'; \
	elif command -v shellcheck >/dev/null 2>&1; then \
		shellcheck $$files; \
	else \
		echo 'shellcheck is not installed; skipping (the CI job runs it when available)'; \
	fi

package: validate-lock secret-scan
	@$(PYTHON) release/package.py --repo-root . --version $(VERSION) --output-dir $(DIST_DIR)

package-verify:
	@$(PYTHON) release/verify_reproducibility.py --repo-root . --version $(VERSION)

inventory:
	@mkdir -p $(DIST_DIR)
	@$(PYTHON) release/inventory.py --repo-root . --output $(DIST_DIR)/component-inventory.json

release-test: validate-lock secret-scan unit package package-verify
	@echo 'Release packaging checks passed'
