`timescale 1ns/1ps
`default_nettype none

// Only package ports: no hierarchy, force, probes or RTL-only parameters.
module tb_pins;
    reg clk, rst_n;
    reg [7:0] ui_in;
    reg [3:0] gpio_external;
    reg slave_scl_low, slave_sda_low;
    wire [7:0] uo_out, uio_out, uio_oe;
    wire scl = ~(uio_oe[0] | slave_scl_low);
    wire sda = ~(uio_oe[1] | slave_sda_low);
    wire [3:0] gpio_pads = (uio_out[7:4] & uio_oe[7:4]) |
                               (gpio_external & ~uio_oe[7:4]);
    wire [7:0] uio_in = {gpio_pads, 2'b00, sda, scl};
    tt_um_llr_hepiarisc chip (
        .clk(clk), .rst_n(rst_n), .ena(1'b1),
        .ui_in(ui_in), .uo_out(uo_out),
        .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe)
    );
endmodule
`default_nettype wire
