.PHONY: check smoke validate

PYTHON ?= python3
PYTHON_ENV = PYTHONPATH=src PYTHONPYCACHEPREFIX=build/pycache

check:
	$(PYTHON_ENV) $(PYTHON) -m compileall -q src tests
	$(PYTHON_ENV) $(PYTHON) -m unittest discover -s tests -v
	$(PYTHON_ENV) $(PYTHON) -m rimf_lab validate-repository --root .

validate:
	$(PYTHON_ENV) $(PYTHON) -m rimf_lab validate-repository --root .

smoke:
	mkdir -p artifacts
	$(PYTHON_ENV) $(PYTHON) -m rimf_lab run \
		--scenario qualification/scenarios/harness-smoke.json \
		--output artifacts/harness-smoke-result.json
