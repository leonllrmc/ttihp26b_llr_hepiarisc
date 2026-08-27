module hepiarisc_alu (
  input [7:0] data_A,
  input [7:0] data_B,

  input [2:0] alu_opcode,

  output [7:0] result_out,

  output flag_overflow,
  output flag_carry,
  output flag_zero,
  output flag_negative
);

reg [7:0] result_int;
assign result_out = result_int[7:0];

always_comb begin
    case(alu_opcode)
        3'b000: result_int = data_A + data_B;
        3'b001: result_int = data_A - data_B;
        3'b010: result_int = {data_A[6:0], 1'b0};// << 1
        3'b011: result_int = {1'b0, data_A[7:1]};// >> 1
        3'b100: result_int = {data_A[7], data_A[7:1]};// ASR = >> but keep sign bit
        3'b101: result_int = data_A & data_B;
        3'b110: result_int = data_A | data_B;
        3'b111: result_int = ~data_A;
    endcase
end

assign flag_zero = (result_out == 8'h00);
assign flag_negative = result_out[7];

wire [8:0] addition_result_ovf = data_A + data_B;
wire [8:0] sub_result_ovf = data_A - data_B;

assign flag_carry = (alu_opcode == 3'b000) ? addition_result_ovf[8] :
                    (alu_opcode == 3'b001) ? sub_result_ovf[8] :
                    (alu_opcode == 3'b010) ? data_A[7] :
                    (alu_opcode == 3'b011) ? data_A[0] :
                    (alu_opcode == 3'b100) ? data_A[0] : 1'b0;

wire add_sub_overflow = (~(data_A[7] ^ ~(data_B[7])) && (~(data_B[7]) ^ result_out[7]));
assign flag_overflow = (alu_opcode == 3'b000) ? add_sub_overflow :
                      (alu_opcode == 3'b001) ? add_sub_overflow :
                      (alu_opcode == 3'b100) ? ~(data_A[7] ^ data_A[6]) : 1'b0;

endmodule
