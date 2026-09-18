// -----------------------------------------------------------------------------
// i2c_master.v
// also made with claude because I was too lazy
//
// Simple single-master I2C controller with byte-level transactions,
// transparent clock stretching, and a pre-settable ACK/NAK response for
// received bytes.
//
// Timing: every bit (and the START/STOP edges) takes 4 quarter-periods of
// CLK_DIV clk cycles each:
//   PH0 : SCL low,  data driven / setup
//   PH1 : SCL low,  hold (extra setup margin)
//   PH2 : SCL released (may stretch here), wait for it to actually go high
//   PH3 : SCL high, sample / close the bit (drives SCL low again)
// SCL frequency ~= clk_freq / (4 * CLK_DIV).
//
// Bus model: scl_oe/sda_oe = 1 drives the corresponding line low; = 0
// releases it to the external pull-up. scl_in/sda_in must reflect the
// actual pad state (so a slave holding SCL low is visible on scl_in).
// -----------------------------------------------------------------------------

module i2c_master #(
    parameter CLK_DIV     = 20,  // quarter-bit-period, in clk cycles
    parameter DEFAULT_NAK = 1    // 1 = default recv_byte response is NAK, 0 = ACK
)(
    input  wire       clk,
    input  wire       rst_n,

    // Open-drain bus interface
    input  wire       scl_in,
    output reg        scl_oe,
    input  wire       sda_in,
    output reg        sda_oe,

    // Commands (all 1-cycle pulses unless noted)
    input  wire       start,
    input  wire       stop,

    input  wire       send_byte,
    input  wire [7:0] din,

    input  wire       recv_byte,
    output reg  [7:0] dout,

    input  wire       set_ack,
    input  wire       set_nak,

    // Status
    output reg        ack_bit,
    output reg        byte_done,
    output reg        start_done,
    output reg        stop_done,
    output reg        busy
);

    // ---------------------------------------------------------------
    // States / phases
    // ---------------------------------------------------------------
    localparam S_IDLE  = 2'd0;
    localparam S_START = 2'd1;
    localparam S_STOP  = 2'd2;
    localparam S_BIT   = 2'd3;

    localparam PH0 = 2'd0;
    localparam PH1 = 2'd1;
    localparam PH2 = 2'd2;
    localparam PH3 = 2'd3;

    reg [1:0]  state;
    reg [1:0]  phase;
    reg [15:0] qcnt;

    reg [3:0]  bit_cnt;    // 0..8  (8 data bits, then the ACK/NAK bit)
    reg        op_tx;      // 1 = send_byte in progress, 0 = recv_byte
    reg [7:0]  shreg;      // TX source shifted out of / RX byte shifted into
    reg        ack_preset; // 1 = respond ACK, 0 = respond NAK on next recv_byte

    // Pause the quarter-period counter whenever we've just asked to release
    // SCL but a slave (or someone else) is still holding it low.
    wire can_advance =
        !( (state == S_START && phase == PH0 && !scl_in) ||
           (state == S_STOP  && phase == PH2 && !scl_in) ||
           (state == S_BIT   && phase == PH2 && !scl_in) );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            phase      <= PH0;
            qcnt       <= 16'd0;
            scl_oe     <= 1'b0;
            sda_oe     <= 1'b0;
            busy       <= 1'b0;
            byte_done  <= 1'b0;
            start_done <= 1'b0;
            stop_done  <= 1'b0;
            bit_cnt    <= 4'd0;
            op_tx      <= 1'b0;
            shreg      <= 8'h00;
            dout       <= 8'h00;
            ack_bit    <= 1'b0;
            ack_preset <= (DEFAULT_NAK != 0) ? 1'b0 : 1'b1;
        end else begin
            // Status pulses are 1 cycle wide unless re-asserted below.
            byte_done  <= 1'b0;
            start_done <= 1'b0;
            stop_done  <= 1'b0;

            // ACK/NAK preset can be changed at any time, busy or not.
            if (set_ack)      ack_preset <= 1'b1;
            else if (set_nak) ack_preset <= 1'b0;

            case (state)

                // -----------------------------------------------------
                S_IDLE: begin
                    if (start) begin
                        state  <= S_START;
                        phase  <= PH0;
                        qcnt   <= 16'd0;
                        busy   <= 1'b1;
                        scl_oe <= 1'b0;      // release SCL
                        sda_oe <= 1'b0;      // release SDA
                    end else if (stop) begin
                        state  <= S_STOP;
                        phase  <= PH0;
                        qcnt   <= 16'd0;
                        busy   <= 1'b1;
                        scl_oe <= 1'b1;      // ensure SCL low
                        sda_oe <= 1'b1;      // ensure SDA low
                    end else if (send_byte) begin
                        state   <= S_BIT;
                        phase   <= PH0;
                        qcnt    <= 16'd0;
                        busy    <= 1'b1;
                        op_tx   <= 1'b1;
                        bit_cnt <= 4'd0;
                        shreg   <= din;
                        scl_oe  <= 1'b1;     // ensure SCL low
                        sda_oe  <= ~din[7];  // drive first (MSB) bit
                    end else if (recv_byte) begin
                        state   <= S_BIT;
                        phase   <= PH0;
                        qcnt    <= 16'd0;
                        busy    <= 1'b1;
                        op_tx   <= 1'b0;
                        bit_cnt <= 4'd0;
                        scl_oe  <= 1'b1;     // ensure SCL low
                        sda_oe  <= 1'b0;     // release, slave drives data
                    end
                end

                // -----------------------------------------------------
                S_START: begin
                    if (can_advance) begin
                        if (qcnt == CLK_DIV - 1) begin
                            qcnt <= 16'd0;
                            case (phase)
                                PH0: phase <= PH1;                          // SCL/SDA confirmed released
                                PH1: begin phase <= PH2; sda_oe <= 1'b1; end // SDA falls, SCL high -> START
                                PH2: begin phase <= PH3; scl_oe <= 1'b1; end // SCL driven low again
                                PH3: begin
                                    state      <= S_IDLE;
                                    busy       <= 1'b0;
                                    start_done <= 1'b1;
                                end
                            endcase
                        end else begin
                            qcnt <= qcnt + 16'd1;
                        end
                    end
                end

                // -----------------------------------------------------
                S_STOP: begin
                    if (can_advance) begin
                        if (qcnt == CLK_DIV - 1) begin
                            qcnt <= 16'd0;
                            case (phase)
                                PH0: phase <= PH1;                          // SCL/SDA confirmed low
                                PH1: begin phase <= PH2; scl_oe <= 1'b0; end // release SCL
                                PH2: begin phase <= PH3; sda_oe <= 1'b0; end // SDA rises, SCL high -> STOP
                                PH3: begin
                                    state     <= S_IDLE;
                                    busy      <= 1'b0;
                                    stop_done <= 1'b1;
                                end
                            endcase
                        end else begin
                            qcnt <= qcnt + 16'd1;
                        end
                    end
                end

                // -----------------------------------------------------
                S_BIT: begin
                    if (can_advance) begin
                        if (qcnt == CLK_DIV - 1) begin
                            qcnt <= 16'd0;
                            case (phase)
                                PH0: phase <= PH1;                          // data held, setup margin

                                PH1: begin phase <= PH2; scl_oe <= 1'b0; end // release SCL for this bit

                                PH2: begin
                                    phase <= PH3;
                                    // SCL confirmed high here - sample the line
                                    if (bit_cnt < 4'd8) begin
                                        if (!op_tx)
                                            shreg <= {shreg[6:0], sda_in}; // shift in data bit
                                    end else begin
                                        if (op_tx)
                                            ack_bit <= sda_in;             // sample slave's ACK/NAK
                                    end
                                end

                                PH3: begin
                                    scl_oe <= 1'b1; // drive SCL low, closing this bit
                                    if (bit_cnt < 4'd8) begin
                                        bit_cnt <= bit_cnt + 4'd1;
                                        phase   <= PH0;
                                        if (bit_cnt + 4'd1 < 4'd8) begin
                                            // set up the next data bit
                                            sda_oe <= op_tx ? ~shreg[7 - (bit_cnt + 4'd1)] : 1'b0;
                                        end else begin
                                            // set up the ACK/NAK bit
                                            sda_oe <= op_tx ? 1'b0 : (ack_preset ? 1'b1 : 1'b0);
                                        end
                                    end else begin
                                        // just finished the ACK/NAK bit - byte complete
                                        state     <= S_IDLE;
                                        busy      <= 1'b0;
                                        byte_done <= 1'b1;
                                        if (!op_tx)
                                            dout <= shreg;
                                    end
                                end
                            endcase
                        end else begin
                            qcnt <= qcnt + 16'd1;
                        end
                    end
                end

            endcase
        end
    end

endmodule