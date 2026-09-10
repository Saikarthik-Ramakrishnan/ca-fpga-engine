# Makefile for the C++ engine. Run from software_prototype/cpp/.
#
#   make test          golden vectors, then every correctness layer (-O3 build)
#   make tsan          the same suite under ThreadSanitizer
#   make races         the negative controls, plain build
#   make tsan-matrix   the negative controls under ThreadSanitizer: which
#                      bugs the tool sees and which it cannot
#   make tsan-probe    40 lines showing TSan misjudge std::barrier on macOS
#   make tsan-stdbarrier  the std::barrier engines under TSan (informational)
#   make prove         exhaustive schedule exploration (the model checker)
#   make bench         laptop throughput and latency, written to results/
#   make check         test + tsan + tsan-matrix + prove, everything CI runs
#
# golden_rule.py is the only reference. The vectors are regenerated
# whenever it changes, and nothing here compares C++ against C++ without
# the chain of trust leading back to it.

CXX       ?= c++
PYTHON    ?= python3
STD       := -std=c++20
WARN      := -Wall -Wextra -Wpedantic
INC       := -Iinclude
ARCH      := $(shell uname -m)
ifeq ($(ARCH),arm64)
  NATIVE  ?= -mcpu=native
else
  NATIVE  ?= -march=native
endif
OPT       := -O3 $(NATIVE)
TSAN      := -O1 -g -fsanitize=thread -fno-omit-frame-pointer
LDLIBS    := -pthread

BUILD     := build
VEC       := $(BUILD)/vectors
GOLDEN    := ../parallelism_ladder/golden_rule.py
HDRS      := $(wildcard include/cellnet/*.hpp)

.PHONY: all vectors test tsan tsan-stdbarrier tsan-probe races tsan-matrix prove bench check clean

all: $(BUILD)/test_correctness $(BUILD)/races $(BUILD)/bench

$(BUILD):
	mkdir -p $(BUILD)

# ---- golden vectors ----
$(VEC)/.stamp: tools/gen_vectors.py $(GOLDEN)
	$(PYTHON) tools/gen_vectors.py $(VEC)
	touch $@

vectors: $(VEC)/.stamp

# ---- binaries ----
$(BUILD)/test_correctness: src/test_correctness.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(OPT) $(INC) $< -o $@ $(LDLIBS)

$(BUILD)/test_correctness_tsan: src/test_correctness.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(TSAN) $(INC) $< -o $@ $(LDLIBS)

$(BUILD)/races: src/races.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(OPT) $(INC) $< -o $@ $(LDLIBS)

$(BUILD)/races_tsan: src/races.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(TSAN) $(INC) $< -o $@ $(LDLIBS)

$(BUILD)/tsan_barrier_probe: src/tsan_barrier_probe.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(TSAN) $(INC) $< -o $@ $(LDLIBS)

$(BUILD)/bench: src/bench.cpp $(HDRS) | $(BUILD)
	$(CXX) $(STD) $(WARN) $(OPT) $(INC) $< -o $@ $(LDLIBS)

# ---- runs ----
test: $(BUILD)/test_correctness vectors
	$(BUILD)/test_correctness --vectors $(VEC)

# Under TSan the exhaustive layer 2 is skipped: it is single-threaded, so
# TSan has nothing to watch there, and it already passed in `make test`.
# abort_on_error=0: on macOS sanitizers default to abort() after a report,
# which turns exit code 66 into SIGABRT (134). This keeps it 66 everywhere.
TSAN_ENV := abort_on_error=0 exitcode=66

tsan: $(BUILD)/test_correctness_tsan vectors
	TSAN_OPTIONS="halt_on_error=1 $(TSAN_ENV)" \
	$(BUILD)/test_correctness_tsan --vectors $(VEC) --skip-exhaustive --stress 60

# Not gating: reports whatever TSan says about the std::barrier family on
# this platform. On macOS that is a false positive; see tsan-probe.
tsan-stdbarrier: $(BUILD)/test_correctness_tsan vectors
	-TSAN_OPTIONS="halt_on_error=0 $(TSAN_ENV)" \
	$(BUILD)/test_correctness_tsan --vectors $(VEC) --skip-exhaustive --stress 20 --include-stdbarrier \
	  > $(BUILD)/tsan_stdbarrier.log 2>&1; \
	echo "std::barrier family under TSan: exit $$?, $$(grep -c 'WARNING: ThreadSanitizer' $(BUILD)/tsan_stdbarrier.log) report(s); log in $(BUILD)/tsan_stdbarrier.log"; \
	grep -E '^RESULT' $(BUILD)/tsan_stdbarrier.log || true

tsan-probe: $(BUILD)/tsan_barrier_probe
	@echo "== AtomicBarrier (every operation instrumented) =="
	@TSAN_OPTIONS="halt_on_error=0 $(TSAN_ENV)" $(BUILD)/tsan_barrier_probe atomic 2>&1 | grep -E 'sum|WARNING' ; true
	@echo "== std::barrier (arrival tree inside libc++.dylib) =="
	@TSAN_OPTIONS="halt_on_error=0 $(TSAN_ENV)" $(BUILD)/tsan_barrier_probe std 2>&1 | grep -E 'sum|WARNING' ; true

races: $(BUILD)/races
	$(BUILD)/races

tsan-matrix: $(BUILD)/races_tsan
	./tools/tsan_matrix.sh $(BUILD)/races_tsan

prove:
	$(PYTHON) tools/prove_schedules.py

bench: $(BUILD)/bench
	mkdir -p results
	$(BUILD)/bench --out results/laptop_bench.csv --machine results/machine.json

check: test tsan tsan-matrix prove

clean:
	rm -rf $(BUILD)
