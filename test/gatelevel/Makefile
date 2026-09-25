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

# --- VCD export -------------------------------------------------------
# Generates a small, never-instantiated Verilog stub that dumps the whole
# TOPLEVEL hierarchy. Icarus elaborates uninstantiated modules as extra
# roots, so this works regardless of whether tb_pins.sv already has its
# own $dumpfile/$dumpvars block. The VCD is written into HEPIA_OUTPUT so
# it ends up wherever your CI already collects build artifacts from.
VCD ?= 1
ifeq ($(VCD),1)
  VCD_FILE := $(HEPIA_OUTPUT)/waveform-$(MODE)-$(SIM).vcd
  VCD_DUMP_V := $(SIM_BUILD)/tt_vcd_dump.v
  VERILOG_SOURCES += $(VCD_DUMP_V)

$(VCD_DUMP_V):
	@mkdir -p $(SIM_BUILD) $(HEPIA_OUTPUT)
	@echo 'module tt_vcd_dump();'              >  $@
	@echo '  initial begin'                     >> $@
	@echo '    $$dumpfile("$(VCD_FILE)");'      >> $@
	@echo '    $$dumpvars(0, $(TOPLEVEL));'     >> $@
	@echo '  end'                               >> $@
	@echo 'endmodule'                           >> $@
endif
# ------------------------------------------------------------------------

include $(shell cocotb-config --makefiles)/Makefile.sim