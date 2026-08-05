# IMU-Based Assistance Dog Alert Verification and Emergency Escalation System
#
#   make help       what each target does
#   make artifacts  regenerate every derived file (results, model, figures)
#   make test       run everything that can be run in this repo
#   make demo       bring up the backend with a seeded alert history

PYTHON ?= python3
PORT   ?= 8080

.PHONY: help artifacts experiments export vectors figures test test-ml \
        test-escalation test-firmware demo replay serve seed clean clean-all

help:
	@echo "Assistance-dog alert escalation system"
	@echo
	@echo "  make artifacts       run experiments, export the model, build figures"
	@echo "  make test            all runnable tests (ML, escalation, firmware core)"
	@echo "  make demo            dev backend + seeded history at http://localhost:$(PORT)/"
	@echo "  make replay          one end-to-end escalation on real data"
	@echo
	@echo "  make experiments     train + evaluate      -> ml/artifacts/results.json"
	@echo "  make export          transpile the model   -> firmware/collar/src/model.h"
	@echo "  make vectors         golden test vectors   -> firmware/test/vectors.bin"
	@echo "  make figures         report figures        -> docs/figures/"
	@echo
	@echo "  backend/ (Jakarta EE) needs Maven and is not built by these targets:"
	@echo "      mvn -f backend/pom.xml package"

# --- artifacts ------------------------------------------------------------- #
artifacts: experiments export vectors figures
	@echo "\nall artifacts regenerated"

experiments:
	$(PYTHON) ml/scripts/run_experiments.py

# The exporter reads the operating point from results.json, so ordering matters.
export: experiments
	$(PYTHON) ml/scripts/export_firmware_model.py

vectors:
	$(PYTHON) ml/scripts/make_firmware_vectors.py

figures: experiments
	$(PYTHON) ml/scripts/make_figures.py

# --- tests ----------------------------------------------------------------- #
test: test-ml test-escalation test-firmware
	@echo "\nall suites passed"

test-ml:
	@echo "=== detection layer ==="
	$(PYTHON) -m pytest ml/tests -q

test-escalation:
	@echo "\n=== escalation layer ==="
	$(PYTHON) -m pytest escalation/tests -q

# Verifies the C against the Python on real dataset windows.
test-firmware: firmware/test/vectors.bin
	@echo "\n=== firmware core ==="
	$(MAKE) -C firmware/test run

firmware/test/vectors.bin:
	$(PYTHON) ml/scripts/make_firmware_vectors.py

# --- demo ------------------------------------------------------------------ #
demo:
	@echo "starting the dev backend on port $(PORT) ..."
	@$(PYTHON) tools/devserver.py --port $(PORT) & echo $$! > .devserver.pid
	@sleep 2
	@$(PYTHON) tools/seed_demo.py --backend http://localhost:$(PORT)
	@echo "\ndashboard: http://localhost:$(PORT)/"
	@echo "stop with: kill \`cat .devserver.pid\`"

serve:
	$(PYTHON) tools/devserver.py --port $(PORT)

seed:
	$(PYTHON) tools/seed_demo.py --backend http://localhost:$(PORT)

replay:
	$(PYTHON) gateway/replay.py --scenario asleep

# --- housekeeping ---------------------------------------------------------- #
clean:
	$(MAKE) -C firmware/test clean
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
	rm -f .devserver.pid

# Also removes generated artifacts. `make artifacts` rebuilds them all.
clean-all: clean
	rm -rf ml/artifacts docs/figures data
	rm -f firmware/test/vectors.bin firmware/collar/src/model.h
