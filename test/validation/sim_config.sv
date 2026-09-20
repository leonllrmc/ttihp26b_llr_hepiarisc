// Keep the production I2C clock divider when cocotb's Icarus makefile defines
// COCOTB_SIM. This file must be preprocessed before project.sv.
`ifdef COCOTB_SIM
`undef COCOTB_SIM
`endif
