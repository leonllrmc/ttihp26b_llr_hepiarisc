//
// Module: uart_rx
//
// Notes:
// - UART receiver module.
// - Drop-in replacement for the original: identical module name, port
//   list, and parameter names/defaults.
//
// Fixes vs. the original this replaces:
//   1. STOP_BITS was declared but never used anywhere in the FSM — the
//      receiver always behaved as if STOP_BITS=1. It is now honored;
//      for the default STOP_BITS=1 the timing is bit-for-bit identical
//      to the original.
//   2. The START state blindly waited a full bit period with no re-check
//      that the line was still low, so a narrow glitch on uart_rxd could
//      be mistaken for a start bit. It's now re-sampled at the midpoint
//      of the start bit and aborted back to FSM_IDLE if the line has
//      already gone high.
//   3. cycle_counter relied on an implicit "already zero" invariant that
//      only held because the original FSM had no early-abort path. It is
//      now explicitly reset whenever the FSM is in FSM_IDLE, so the new
//      abort path in (2) can't leave a stale count that would misalign
//      the timing of the next byte.
//   4. Removed dead/commented-out code and an unused loop variable.
//

module uart_rx(
input  wire       clk          , // Top level system clock input.
input  wire       resetn       , // Asynchronous active low reset.
input  wire       uart_rxd     , // UART Recieve pin.
input  wire       uart_rx_en   , // Recieve enable
output wire       uart_rx_break, // Did we get a BREAK message?
output wire       uart_rx_valid, // Valid data recieved and available.
output reg  [PAYLOAD_BITS-1:0] uart_rx_data   // The recieved data.
);

// ---------------------------------------------------------------------------
// External parameters.
//

//
// Input bit rate of the UART line.
parameter   BIT_RATE        = 115200; // bits / sec

//
// Clock frequency in hertz.
parameter   CLK_HZ          =    50_000_000;

//
// Number of data bits recieved per UART packet.
parameter   PAYLOAD_BITS    = 8;

//
// Number of stop bits indicating the end of a packet.
parameter   STOP_BITS       = 1;

// ---------------------------------------------------------------------------
// Internal parameters.
//

//
// Number of clock cycles per uart bit.
localparam       CYCLES_PER_BIT     = CLK_HZ / BIT_RATE;

//
// Number of clock cycles spanning the whole stop-bit field.
localparam       CYCLES_PER_STOP    = CYCLES_PER_BIT * STOP_BITS;

//
// Point within the STOP state at which we consider the frame finished and
// re-arm for the next start bit. Mirrors the original's "leave stop state
// half a bit period early" behaviour, generalised to STOP_BITS stop bits
// (for STOP_BITS=1 this is numerically identical to the original).
localparam       STOP_EXIT_CYCLES   = CYCLES_PER_STOP - CYCLES_PER_BIT/2;

//
// Size of the registers which store sample counts and bit durations.
localparam       COUNT_REG_LEN      = $clog2(CYCLES_PER_STOP + 1);

// ---------------------------------------------------------------------------
// Internal registers.
//

//
// Internally latched value of the uart_rxd line. Helps break long timing
// paths from input pins into the logic, and doubles as a 2-flop
// synchroniser for the asynchronous input.
reg rxd_reg;
reg rxd_reg_0;

//
// Storage for the recieved serial data.
reg [PAYLOAD_BITS-1:0] received_data;

//
// Counter for the number of cycles over a packet bit.
reg [COUNT_REG_LEN-1:0] cycle_counter;

//
// Counter for the number of recieved bits of the packet.
reg [3:0] bit_counter;

//
// Sample of the UART input line taken at the middle of each data bit.
reg bit_sample;

//
// Current and next states of the internal FSM.
reg [2:0] fsm_state;
reg [2:0] n_fsm_state;

localparam FSM_IDLE = 0;
localparam FSM_START= 1;
localparam FSM_RECV = 2;
localparam FSM_STOP = 3;

// ---------------------------------------------------------------------------
// Output assignment
//

assign uart_rx_break = uart_rx_valid && ~|received_data;
assign uart_rx_valid = fsm_state == FSM_STOP && n_fsm_state == FSM_IDLE;

always @(posedge clk) begin
    if(!resetn) begin
        uart_rx_data  <= {PAYLOAD_BITS{1'b0}};
    end else if (fsm_state == FSM_STOP) begin
        uart_rx_data  <= received_data;
    end
end

// ---------------------------------------------------------------------------
// FSM next state selection.
//

// Fires once per bit period: at the end of a full bit period in
// START/RECV, or at STOP_EXIT_CYCLES (partway into the final stop bit)
// in STOP.
wire next_bit     = (fsm_state == FSM_STOP) ? cycle_counter == STOP_EXIT_CYCLES :
                                               cycle_counter == CYCLES_PER_BIT;

// Midpoint of the start bit — used to re-check the line is still low
// before committing to a receive, rejecting glitches shorter than half a
// bit period.
wire start_mid    = cycle_counter == CYCLES_PER_BIT/2;

wire payload_done = bit_counter   == PAYLOAD_BITS;

//
// Handle picking the next state.
always @(*) begin : p_n_fsm_state
    case(fsm_state)
        FSM_IDLE : n_fsm_state = rxd_reg               ? FSM_IDLE  : FSM_START;
        FSM_START: n_fsm_state = (start_mid && rxd_reg)? FSM_IDLE  :
                                  next_bit              ? FSM_RECV :
                                                           FSM_START;
        FSM_RECV : n_fsm_state = payload_done          ? FSM_STOP  : FSM_RECV;
        FSM_STOP : n_fsm_state = next_bit              ? FSM_IDLE  : FSM_STOP;
        default  : n_fsm_state = FSM_IDLE;
    endcase
end

// ---------------------------------------------------------------------------
// Internal register setting and re-setting.
//

//
// Handle updates to the recieved data register.
always @(posedge clk) begin : p_received_data
    if(!resetn) begin
        received_data <= {PAYLOAD_BITS{1'b0}};
    end else if(fsm_state == FSM_IDLE             ) begin
        received_data <= {PAYLOAD_BITS{1'b0}};
    end else if(fsm_state == FSM_RECV && next_bit ) begin
        received_data <= {bit_sample, received_data[PAYLOAD_BITS-1:1]};
    end
end

//
// Increments the bit counter when recieving.
always @(posedge clk) begin : p_bit_counter
    if(!resetn) begin
        bit_counter <= 4'b0;
    end else if(fsm_state != FSM_RECV) begin
        bit_counter <= 4'b0;
    end else if(fsm_state == FSM_RECV && next_bit) begin
        bit_counter <= bit_counter + 1'b1;
    end
end

//
// Sample the recieved bit at the middle of each data bit frame.
always @(posedge clk) begin : p_bit_sample
    if(!resetn) begin
        bit_sample <= 1'b0;
    end else if (fsm_state == FSM_RECV && cycle_counter == CYCLES_PER_BIT/2) begin
        bit_sample <= rxd_reg;
    end
end

//
// Increments the cycle counter while receiving; explicitly held at zero
// in FSM_IDLE so a fresh start bit always begins timing from a known
// state (this also makes the FSM_START glitch-abort path in (2) above
// safe — without this, aborting mid-start-bit would leave a stale,
// non-zero count that misaligns the timing of the next byte).
always @(posedge clk) begin : p_cycle_counter
    if(!resetn) begin
        cycle_counter <= {COUNT_REG_LEN{1'b0}};
    end else if(fsm_state == FSM_IDLE) begin
        cycle_counter <= {COUNT_REG_LEN{1'b0}};
    end else if(next_bit) begin
        cycle_counter <= {COUNT_REG_LEN{1'b0}};
    end else begin
        cycle_counter <= cycle_counter + 1'b1;
    end
end

//
// Progresses the next FSM state.
always @(posedge clk) begin : p_fsm_state
    if(!resetn) begin
        fsm_state <= FSM_IDLE;
    end else begin
        fsm_state <= n_fsm_state;
    end
end

//
// Responsible for updating the internal value of the rxd_reg.
always @(posedge clk) begin : p_rxd_reg
    if(!resetn) begin
        rxd_reg     <= 1'b1;
        rxd_reg_0   <= 1'b1;
    end else if(uart_rx_en) begin
        rxd_reg     <= rxd_reg_0;
        rxd_reg_0   <= uart_rxd;
    end
end

endmodule