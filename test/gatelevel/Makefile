HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(HERE)/../..)
MODE ?= $(if $(filter yes,$(GATES)),gl,rtl)
SIM ?= $(if $(filter gl,$(MODE)),icarus,icarus)
TOPLEVEL_LANG = verilog
TOPLEVEL = tb_pins
COCOTB_TEST_MODULES = test_global
SIM_BUILD ?= $(HERE)/build/$(MODE)-$(SIM)
COCOTB_RESULTS_FILE ?= $(HERE)/results.xml
GL_NETLIST ?= $(HERE)/gate_level_netlist.v
export HEPIA_GL_MODE ?= $(MODE)
export HEPIA_GL_CLOCK_NS ?= $(shell python3 -c 'import json; print(json.load(open("$(ROOT)/src/config.json"))["CLOCK_PERIOD"])')
export HEPIA_OUTPUT ?= $(HERE)/output
export HEPIA_PROTOCOL ?= 1
export HEPIA_TRACE ?= instructions
export PYTHONPATH := $(HERE):$(ROOT)/test/validation:$(PYTHONPATH)
COMPILE_ARGS += -DFUNCTIONAL -DSIM

ifeq ($(MODE),gl)
  ifeq ($(strip $(GL_NETLIST)),)
    $(error GL_NETLIST must name the actual synthesized netlist)
  endif
  ifeq ($(strip $(PDK_ROOT)),)
    $(error PDK_ROOT must contain ihp-sg13g2/libs.ref)
  endif
  VERILOG_SOURCES = $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_stdcell/verilog/sg13g2_stdcell.v
  VERILOG_SOURCES += $(PDK_ROOT)/ihp-sg13g2/libs.ref/sg13g2_io/verilog/sg13g2_io.v
  VERILOG_SOURCES += $(GL_NETLIST)
else ifeq ($(MODE),rtl)
  VERILOG_SOURCES = $(ROOT)/test/validation/sim_config.sv
  VERILOG_SOURCES += $(addprefix $(ROOT)/src/,project.sv hepiarisc.sv hepiarisc_alu.sv hepiarisc_regbank.sv spi_master.v systick_gen.sv i2c_master.v uart_rx.v uart_tx.v)
else
  $(error MODE must be rtl or gl)
endif
VERILOG_SOURCES += $(HERE)/tb_pins.sv
ifeq ($(SIM),verilator)
  EXTRA_ARGS += --no-timing -Wno-fatal
else ifeq ($(SIM),icarus)
  COMPILE_ARGS += -g2012
endif

# --- Force a real tb.vcd no matter what ---------------------------------
# The CI's artifact-upload step looks for a literal "tb.vcd" right here
# in test/gatelevel/. Two defenses, unconditional, independent of
# pass/fail:
#  1. Neutralize WAVES so nothing (cocotb's own icarus WAVES handling,
#     or a WAVES env var set by the CI) puts Icarus into -fst mode,
#     which silently redirects $dumpfile("tb.vcd") into tb.fst.
#  2. Inject our own never-instantiated dump module, so a VCD gets
#     written even if tb_pins.sv has no dump code of its own. Icarus
#     elaborates uninstantiated modules as extra roots.
override WAVES :=
unexport WAVES

TB_VCD := $(HERE)/tb.vcd
FORCE_VCD_V := $(SIM_BUILD)/force_vcd_dump.v
# Written immediately at parse time (not as a make rule/target) so this
# can't accidentally become the default make goal. mkdir/printf produce
# no stdout, so this expands to nothing in the makefile text.
$(shell mkdir -p $(SIM_BUILD))
$(shell printf '%s\n' \
	'module force_vcd_dump();' \
	'  initial begin' \
	'    $$dumpfile("$(TB_VCD)");' \
	'    $$dumpvars(0, $(TOPLEVEL));' \
	'  end' \
	'endmodule' \
	> $(FORCE_VCD_V))
VERILOG_SOURCES += $(FORCE_VCD_V)
ifeq ($(SIM),icarus)
  # Icarus only auto-roots uninstantiated modules when NO -s flag is
  # given at all. Cocotb's Makefile.icarus already passes "-s
  # $(TOPLEVEL)", which switches Icarus into explicit-root-list mode -
  # so without this, force_vcd_dump is silently never elaborated and
  # never runs. Adding it as a second explicit root fixes that.
  COMPILE_ARGS += -s force_vcd_dump
endif

include $(shell cocotb-config --makefiles)/Makefile.sim