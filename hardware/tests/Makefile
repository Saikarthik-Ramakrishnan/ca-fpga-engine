SIM ?= icarus
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(PWD)/../rtl/ca_cell.v
TOPLEVEL = ca_cell
MODULE = test_ca_cell

# own build dir: suites sharing sim_build serve each other stale binaries
# (cocotb only rebuilds when sources change, not when the Makefile does)
SIM_BUILD = sim_build_cell

include $(shell cocotb-config --makefiles)/Makefile.sim
