`timescale 1ns/1ps
`default_nettype none

module tb_alu;
    reg [7:0] a, b;
    reg [2:0] op;
    wire [7:0] result;
    wire v, c, z, n;
    hepiarisc_alu dut(a,b,op,result,v,c,z,n);
endmodule

module tb_cpu;
    reg clk, rst_n, enable, irq;
    reg [15:0] instruction;
    reg [7:0] miso;
    wire [7:0] pc, mosi, address;
    wire [3:0] bank;
    wire wr, rd;
    hepiarisc cpu(.CLK(clk),.rst_n(rst_n),.enable(enable),.irq(irq),
        .instruction_in(instruction),.instruction_addr(pc),.instruction_addr_bank(bank),
        .extmem_MISO(miso),.extmem_MOSI(mosi),.extmem_addr(address),.extmem_wr(wr),.extmem_rd(rd));
    wire [63:0] registers;
    wire [3:0] flags = {cpu.alu_flag_negative,cpu.alu_flag_zero,cpu.alu_flag_carry,cpu.alu_flag_overflow};
    wire [2:0] sp = cpu.bankjmp_SP;
    wire [7:0] irq_pc = cpu.IRQ_latched_PC;
    wire [3:0] irq_bank = cpu.IRQ_prev_bank;
    wire [3:0] irq_flags = {cpu.irq_latched_flag_negative,cpu.irq_latched_flag_zero,cpu.irq_latched_flag_carry,cpu.irq_latched_flag_overflow};
    wire [95:0] stack;
    genvar i;
    generate for(i=0;i<8;i=i+1) begin
        assign registers[8*i+:8] = cpu.regbank.registers[i];
        assign stack[12*i+:12] = {cpu.returnBank[i],cpu.bankJumpReturnAddr[i]};
    end endgenerate
endmodule

module tb_systick;
    reg clk, rst_n, en;
    reg [7:0] divider;
    wire irq_pulse;
    wire [7:0] systick_counter_out;
    systick_gen #(.min_div(8)) dut(clk,rst_n,divider,en,irq_pulse,systick_counter_out);
endmodule

`ifndef VALIDATION_SPI_DIV
`define VALIDATION_SPI_DIV 4
`endif
module tb_spi;
    reg clk, rst_n, miso, send;
    reg [7:0] din;
    wire sclk, mosi, cs_n, done, busy;
    wire [7:0] dout;
    spi_master #(.CLK_DIV(`VALIDATION_SPI_DIV)) dut(clk,rst_n,sclk,mosi,miso,cs_n,send,din,dout,done,busy);
endmodule

module tb_i2c;
    reg clk, rst_n, start, stop, send_byte, recv_byte, set_ack, set_nak;
    reg [7:0] din;
    reg slave_scl_low, slave_sda_low;
    wire scl_oe, sda_oe;
    wire scl = ~(scl_oe | slave_scl_low);
    wire sda = ~(sda_oe | slave_sda_low);
    wire [7:0] dout;
    wire ack_bit, byte_done, start_done, stop_done, busy;
    i2c_master #(.CLK_DIV(4),.DEFAULT_NAK(0)) dut(
        .clk(clk),.rst_n(rst_n),.scl_in(scl),.scl_oe(scl_oe),.sda_in(sda),.sda_oe(sda_oe),
        .start(start),.stop(stop),.send_byte(send_byte),.din(din),.recv_byte(recv_byte),
        .dout(dout),.set_ack(set_ack),.set_nak(set_nak),.ack_bit(ack_bit),
        .byte_done(byte_done),.start_done(start_done),.stop_done(stop_done),.busy(busy));
endmodule

module tb_soc;
    reg clk, rst_n;
    reg [7:0] ui_in;
    reg [3:0] gpio_external;
    reg slave_scl_low, slave_sda_low;
    wire [7:0] uo_out, uio_out, uio_oe;
    wire scl = ~(uio_oe[0] | slave_scl_low);
    wire sda = ~(uio_oe[1] | slave_sda_low);
    wire [3:0] gpio_pads = (uio_out[7:4] & uio_oe[7:4]) | (gpio_external & ~uio_oe[7:4]);
    wire [7:0] uio_in = {gpio_pads,2'b00,sda,scl};
    tt_um_llr_hepiarisc dut(.clk(clk),.rst_n(rst_n),.ena(1'b1),.ui_in(ui_in),
        .uo_out(uo_out),.uio_in(uio_in),.uio_out(uio_out),.uio_oe(uio_oe));
    wire [31:0] i2c_divider = dut.hepiariscTop.i2c_master_phy.CLK_DIV;
    wire [7:0] pc = dut.hepiariscTop.hepiarisc_addr;
    wire [3:0] bank = dut.hepiariscTop.hepiarisc_addr_bank;
    wire cpu_enable = dut.hepiariscTop.hepiarisc_en;
    wire [15:0] instruction = dut.hepiariscTop.hepiarisc_instruction;
    wire [3:0] state = dut.hepiariscTop.currentState;
    wire [3:0] flags = {dut.hepiariscTop.cpu.alu_flag_negative,dut.hepiariscTop.cpu.alu_flag_zero,dut.hepiariscTop.cpu.alu_flag_carry,dut.hepiariscTop.cpu.alu_flag_overflow};
    wire [63:0] registers;
    wire [2:0] sp = dut.hepiariscTop.cpu.bankjmp_SP;
    wire irq_pending = dut.hepiariscTop.hepiarisc_irq_latched;
    wire irq_raw = dut.hepiariscTop.hepiarisc_irq;
    wire irq_external = dut.hepiariscTop.irq_ext_pulse;
    wire systick_irq = dut.hepiariscTop.systick_irq;
    wire [1:0] irq_sources = dut.hepiariscTop.IRQ_source_en;
    wire [7:0] systick_divider = dut.hepiariscTop.systick_divider;
    wire timer_reload = dut.hepiariscTop.systick_reg_reload;
    wire i2c_busy = dut.hepiariscTop.I2C_busy;
    wire [7:0] mem_address = dut.hepiariscTop.hepiarisc_memop_address;
    wire [7:0] mem_write_data = dut.hepiariscTop.hepiarisc_memop_output;
    wire [7:0] mem_read_data = dut.hepiariscTop.hepiarisc_memop_input;
    wire mem_write = dut.hepiariscTop.hepiarisc_instruction_memop_wr;
    wire mem_read = dut.hepiariscTop.hepiarisc_instruction_memop_rd;
    genvar j;
    generate for(j=0;j<8;j=j+1) begin
        assign registers[8*j+:8] = dut.hepiariscTop.cpu.regbank.registers[j];
    end endgenerate
endmodule

`default_nettype wire
