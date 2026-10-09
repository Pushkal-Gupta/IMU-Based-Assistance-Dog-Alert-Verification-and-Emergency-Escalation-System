# IMU-Based Assistance Dog Alert Verification and Emergency Escalation System
#
#   make help       what each target does
#   make artifacts  regenerate every derived file (results, model, figures)
#   make test       run everything that can be run in this repo
#   make demo       bring up the backend with a seeded alert history

# Prefer the project virtualenv when it exists (python3 -m venv .venv).
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PORT   ?= 8080

.PHONY: help artifacts experiments export vectors figures test test-ml \
        test-escalation test-gateway test-firmware demo replay serve seed clean clean-all \
        all-research research ablations simulation formal properties bench numbers \
        paper-figures paper paper-check

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
	@echo "  research (the paper in paper/):"
	@echo "  make all-research    every analysis below, in dependency order"
	@echo "  make research        intervals, shift, nested, continuous -> ml/artifacts/research.json"
	@echo "  make ablations       baselines, ablations, robustness     -> ml/artifacts/ablations.json"
	@echo "  make simulation      Monte-Carlo escalation outcomes      -> escalation/artifacts/simulation.json"
	@echo "  make formal          TLC model checking                   -> formal/results.json"
	@echo "  make properties      10k-example property tests on the engine"
	@echo "  make bench           host benchmark of the C core         -> firmware/test/bench*.json"
	@echo "  make paper           numbers, figures, PDF                -> paper/build/main.pdf"
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
test: test-ml test-escalation test-gateway test-firmware
	@echo "\nall suites passed"

test-ml:
	@echo "=== detection layer ==="
	$(PYTHON) -m pytest ml/tests -q

test-escalation:
	@echo "\n=== escalation layer ==="
	$(PYTHON) -m pytest escalation/tests -q

test-gateway:
	@echo "\n=== relay ==="
	$(PYTHON) -m pytest gateway/tests -q

# Verifies the C against the Python on real dataset windows.
test-firmware: firmware/test/vectors.bin
	@echo "\n=== firmware core ==="
	$(MAKE) -C firmware/test run

firmware/test/vectors.bin:
	$(PYTHON) ml/scripts/make_firmware_vectors.py

# --- research: everything the paper reports ------------------------------- #
# Order matters: the simulation reads research.json, the paper reads all.
all-research: artifacts research ablations simulation formal properties bench test-firmware paper
	@echo "\nall research artifacts and the paper regenerated"

research:
	$(PYTHON) ml/scripts/run_research.py

ablations:
	$(PYTHON) ml/scripts/run_ablations.py

simulation:
	$(PYTHON) -m escalation.sim.run_sim

TLA_JAR := formal/tla2tools.jar
TLA_URL := https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar

$(TLA_JAR):
	curl -sSL -o $@ $(TLA_URL)

formal: $(TLA_JAR)
	$(PYTHON) formal/run_tlc.py

properties:
	HYPOTHESIS_PROFILE=thorough $(PYTHON) -m pytest escalation/tests/test_properties.py -q

bench:
	$(MAKE) -C firmware/test bench bench-direct

numbers:
	$(PYTHON) paper/scripts/make_numbers.py
	$(PYTHON) paper/scripts/check_numbers.py

paper-figures:
	$(PYTHON) paper/scripts/make_figures.py

# Needs tectonic and ghostscript (brew install tectonic ghostscript).
paper: numbers paper-figures
	$(PYTHON) paper/scripts/make_supplementary.py
	paper/scripts/build_pdf.sh

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
