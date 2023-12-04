.PHONY: help bootstrap lint test requirements

VENV?=.venv
PYTHON?=python3
PYTHONNOUSERSITE?=1

help:
	@echo
	@echo "make install         -- setup production environment"
	@echo
	@echo "make development     -- setup development environment"
	@echo "make test            -- run full test suite"
	@echo "make lint            -- run all linters on the code base"
	@echo
	@echo "make requirements    -- only compile the requirements*.txt files"
	@echo "make .venv           -- bootstrap the virtualenv."
	@echo

PIP_SYNC=$(VENV)/bin/pip-sync

install: $(VENV)/.pip-installed-production

development: $(VENV)/.pip-installed-development .git/hooks/pre-commit

lint: development
	$(VENV)/bin/pre-commit run -a

test: development
	$(VENV)/bin/pytest

requirements: requirements-dev.txt

requirements-dev.txt: pyproject.toml $(PIP_SYNC)
	$(VENV)/bin/pip-compile -v --output-file=$@ --extra=dev --extra=yaml $<

# Actual files/directories
################################################################################

# Create this directory as a symbolic link to an existing virtualenv, if you want to use that.
$(VENV):
	$(PYTHON) -m venv --system-site-packages $(VENV)
	touch $(VENV)

$(PIP_SYNC): $(VENV)
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) $(VENV)/bin/pip install --upgrade pip pip-tools wheel && touch $@

$(VENV)/.pip-installed-development: requirements-dev.txt $(PIP_SYNC)
	PYTHONNOUSERSITE=$(PYTHONNOUSERSITE) $(PIP_SYNC) $< && touch $@

.git/hooks/pre-commit: $(VENV)
	$(VENV)/bin/pre-commit install
	touch .git/hooks/pre-commit
