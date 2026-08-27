module hepiarisc_regbank (
  input CLK,
  input rst_n,

	input [2:0] addr_rd_a,
	output [7:0] data_rd_a,
	input [2:0] addr_rd_b,
	output [7:0] data_rd_b,


  input [7:0] data_wr,
  input [2:0] addr_wr,
	input we,

	input enable
);

	reg [7:0] registers [0:7];

	always @(posedge CLK or negedge rst_n) begin
		if(~rst_n) begin
			// generate makes sim error =(
			registers[0] <= 8'h00;
			registers[1] <= 8'h00;
			registers[2] <= 8'h00;
			registers[3] <= 8'h00;
			registers[4] <= 8'h00;
			registers[5] <= 8'h00;
			registers[6] <= 8'h00;
			registers[7] <= 8'h00;
		end else begin
			if(we && enable) begin
				registers[addr_wr] <= data_wr;
			end
		end
	end

	assign data_rd_a = registers[addr_rd_a];
	assign data_rd_b = registers[addr_rd_b];

endmodule