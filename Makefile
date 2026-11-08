PYTHON ?= .venv/bin/python

.PHONY: check test copilot-check example-check pilot-check wheel

check: test example-check pilot-check
	$(PYTHON) -m pip check

test:
	$(PYTHON) -m unittest discover -s tests -v

copilot-check:
	$(PYTHON) -c 'import importlib.metadata; assert importlib.metadata.version("mcp") == "2.3.0", "Install .[copilot] first"'
	$(PYTHON) -m unittest discover -s tests -p 'test_copilot*.py' -v

example-check:
	$(PYTHON) -B examples/batch-queue/check_idempotency.py

pilot-check:
	$(PYTHON) -B tools/run_pilot.py

wheel:
	$(PYTHON) -m pip wheel --no-deps --wheel-dir dist .
