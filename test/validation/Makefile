# Independent of test/Makefile: the original smoke tests remain available.
SIM ?= verilator
SUITE ?= cpu
TOPLEVEL_LANG = verilog
TOPLEVEL = tb_$(SUITE)
COCOTB_TEST_MODULES = test_$(SUITE)
HERE := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SRC := $(HERE)/../../src
SIM_BUILD ?= $(HERE)/build/$(SIM)-$(SUITE)
SPI_DIV ?= 4
export PYTHONPATH := $(HERE):$(PYTHONPATH)
SOURCES_alu = hepiarisc_alu.sv
SOURCES_cpu = hepiarisc.sv hepiarisc_alu.sv hepiarisc_regbank.sv
SOURCES_systick = systick_gen.sv
SOURCES_spi = spi_master.v
SOURCES_i2c = i2c_master.v
SOURCES_soc = project.sv hepiarisc.sv hepiarisc_alu.sv hepiarisc_regbank.sv spi_master.v systick_gen.sv i2c_master.v uart_tx.v uart_rx.v
VERILOG_SOURCES = $(HERE)/sim_config.sv $(addprefix $(SRC)/,$(SOURCES_$(SUITE))) $(HERE)/benches.sv
COMPILE_ARGS += -DVALIDATION_SPI_DIV=$(SPI_DIV)
ifeq ($(SIM),verilator)
  EXTRA_ARGS += --no-timing -Wno-fatal
else ifeq ($(SIM),icarus)
  COMPILE_ARGS += -g2012
endif
include $(shell cocotb-config --makefiles)/Makefile.sim
