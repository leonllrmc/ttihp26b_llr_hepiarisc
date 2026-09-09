module hepiarisc (
  input wire CLK,
  input wire rst_n,
  input enable,
  
  input [15:0] instruction_in,
  output [7:0] instruction_addr,

  input irq,

  input [7:0] extmem_MISO,
  output [7:0] extmem_MOSI,
  output [7:0] extmem_addr,
  output extmem_wr,
  output extmem_rd
);

wire [7:0] ALU_result;


reg [7:0] PC;
assign instruction_addr = PC;


wire [15:0] instruction = instruction_in;

// TODO: add instruction (maybe a "bank switch")
// MARK: instruction decode
wire is_alu_inst = ~instruction[15];
wire is_ldconst_inst = instruction[15:12] == 4'h8;
wire is_bra_inst = instruction[15:12] == 4'hB;
wire is_brcond_inst = instruction[15:12] == 4'hA;
wire is_bl_inst = instruction[15:12] == 4'hE; // branch link (jsr)
wire is_br_inst = (instruction[15:12] == 4'hF) && ~instruction[0]; // branch return (rts)
wire is_bir_inst = (instruction[15:12] == 4'hF) && instruction[0]; // irq return (rti)
wire is_ldmem_inst = instruction[15:12] == 4'hC;
wire is_stmem_inst = instruction[15:12] == 4'hD;
wire is_mem_inst = is_ldmem_inst || is_stmem_inst;

wire [2:0] ALU_OP = instruction[14:12];
wire [2:0] alu_ins_reg_b_addr = instruction[5:3];
wire [2:0] alu_ins_reg_a_addr = instruction[8:6];
wire [2:0] alu_ins_reg_result_addr = instruction[11:9];

wire [7:0] ldconst_value = instruction[7:0];
wire [2:0] ldconst_dest_reg = instruction[11:9];

wire [7:0] bra_pc_inc_value = instruction[7:0];
wire [3:0] brcond_opcode = instruction[11:8];

wire [5:0] memop_offset_6 = instruction[5:0];
wire [7:0] memop_offset_8 = {{8{memop_offset_6[5]}}, memop_offset_6};
wire [2:0] memop_ptr_reg = instruction[8:6];
wire [2:0] memop_data_reg = instruction[11:9];

wire [2:0] b_link_reg = instruction[11:9];
wire [7:0] bl_PC_addr = instruction[7:0];

// MARK: reg bank
wire [2:0] addr_reg_rd_a = is_br_inst ? b_link_reg : alu_ins_reg_a_addr;
wire [2:0] addr_reg_rd_b = is_stmem_inst ? memop_data_reg : alu_ins_reg_b_addr;
wire [7:0] data_reg_rd_a;
wire [7:0] data_reg_rd_b;
wire regbank_wr = is_ldmem_inst || is_bl_inst || is_alu_inst || is_ldconst_inst;
reg [7:0] data_reg_wr;
wire [2:0] addr_reg_wr = is_ldmem_inst ? memop_data_reg : alu_ins_reg_result_addr;

always_comb begin
    if(is_alu_inst) begin
        data_reg_wr = ALU_result;
    end else if(is_ldconst_inst) begin
        data_reg_wr = ldconst_value;
    end else if(is_bl_inst) begin
        data_reg_wr = PC + 1;
    end else if(is_ldmem_inst) begin
        data_reg_wr = extmem_MISO;
    end else begin
        data_reg_wr = 8'h00;
    end
end

hepiarisc_regbank regbank(
    .CLK(CLK),
    .enable(enable),
    .rst_n(rst_n),

    .addr_rd_a(addr_reg_rd_a),
    .data_rd_a(data_reg_rd_a),
    .addr_rd_b(addr_reg_rd_b),
    .data_rd_b(data_reg_rd_b),


    .data_wr(data_reg_wr),
    .addr_wr(addr_reg_wr),

    .we(regbank_wr)
);


// MARK: ALU

wire flag_overflow;
wire flag_carry;
wire flag_zero;
wire flag_negative;

reg alu_flag_overflow;
reg alu_flag_carry;
reg alu_flag_zero;
reg alu_flag_negative;

wire next_alu_flag_overflow = is_alu_inst ? flag_overflow : alu_flag_overflow;
wire next_alu_flag_carry = is_alu_inst ? flag_carry : alu_flag_carry;
wire next_alu_flag_zero = is_alu_inst ? flag_zero : alu_flag_zero;
wire next_alu_flag_negative = is_alu_inst ? flag_negative : alu_flag_negative;

always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
        alu_flag_overflow <= 1'b0;
        alu_flag_carry <= 1'b0;
        alu_flag_zero <= 1'b0;
        alu_flag_negative <= 1'b0;
    end else begin
        if(is_alu_inst && enable) begin
            alu_flag_overflow <= flag_overflow;
            alu_flag_carry <= flag_carry;
            alu_flag_zero <= flag_zero;
            alu_flag_negative <= flag_negative;
        end else if(is_bir_inst && enable) begin
            alu_flag_overflow <= irq_latched_flag_overflow;
            alu_flag_carry <= irq_latched_flag_carry;
            alu_flag_zero <= irq_latched_flag_zero;
            alu_flag_negative <= irq_latched_flag_negative;
        end
    end
end

hepiarisc_alu ALU (
  .data_A(data_reg_rd_a),
  .data_B(data_reg_rd_b),

  .alu_opcode(ALU_OP),

  .result_out(ALU_result),

  .flag_overflow(flag_overflow),
  .flag_carry(flag_carry),
  .flag_zero(flag_zero),
  .flag_negative(flag_negative)
);


// MARK: brcond eval
reg brcond_cond_true;

always_comb begin
    // TODO: maybe add more compare mode (2 "slots" left)
    case(brcond_opcode)
        4'h0: brcond_cond_true = ~alu_flag_overflow;
        4'h1: brcond_cond_true = alu_flag_overflow;
        4'h2: brcond_cond_true = alu_flag_carry;
        4'h3: brcond_cond_true = ~alu_flag_carry;
        4'h4: brcond_cond_true = alu_flag_negative;
        4'h5: brcond_cond_true = ~alu_flag_negative;
        4'h6: brcond_cond_true = (~alu_flag_zero) && (alu_flag_negative == alu_flag_overflow);
        4'h7: brcond_cond_true = (alu_flag_negative == alu_flag_overflow);
        4'h8: brcond_cond_true = alu_flag_zero; 
        4'h9: brcond_cond_true = ~alu_flag_zero;
        4'hA: brcond_cond_true = (alu_flag_negative != alu_flag_overflow);
        4'hB: brcond_cond_true = alu_flag_zero || (alu_flag_negative != alu_flag_overflow);
        4'hC: brcond_cond_true = alu_flag_carry && (~alu_flag_zero);
        4'hD: brcond_cond_true = (~alu_flag_carry) || alu_flag_zero;
        default: brcond_cond_true = 1'b0;
    endcase
end



reg [7:0] IRQ_latched_PC;

reg irq_latched_flag_overflow;
reg irq_latched_flag_carry;
reg irq_latched_flag_zero;
reg irq_latched_flag_negative;

reg [7:0] next_PC;
wire irq_sig = irq;


//always_ff @(posedge CLK or negedge rst_n) begin
//    if(~rst_n) begin
//        old_irq_n <= 1'b0;
//        irq_sig <= 1'b0;
//    end else begin
//        irq_sig <= ~irq_n && old_irq_n;;
//        old_irq_n <= irq_n;
//    end
//end

always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
        IRQ_latched_PC <= 8'h00;

        irq_latched_flag_overflow <= 1'b0;
        irq_latched_flag_carry <= 1'b0;
        irq_latched_flag_zero <= 1'b0;
        irq_latched_flag_negative <= 1'b0;
    end else begin
        if(enable && irq_sig) begin
            irq_latched_flag_overflow <= next_alu_flag_overflow;
            irq_latched_flag_carry <= next_alu_flag_carry;
            irq_latched_flag_zero <= next_alu_flag_zero;
            irq_latched_flag_negative <= next_alu_flag_negative;

            IRQ_latched_PC <= PC;
        end
    end
end

always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
        PC <= 8'h00;
    end else begin
        if(enable) begin
            if(is_bl_inst) begin
                PC <= bl_PC_addr;
            end else if(is_bra_inst) begin
                PC <= PC + bra_pc_inc_value;
            end else if (is_brcond_inst && brcond_cond_true) begin
                PC <= PC + bra_pc_inc_value;
            end else if(is_br_inst) begin
                PC <= data_reg_rd_a;
            end else if(is_bir_inst) begin
                PC <= IRQ_latched_PC;
            end else if(irq_sig) begin
                PC <= 8'h01;
            end else begin
                PC <= PC + 1;
            end
        end
    end
end

always_comb begin
    if(is_bl_inst) begin
        next_PC = bl_PC_addr;
    end else if(is_bra_inst) begin
        next_PC = PC + bra_pc_inc_value;
    end else if (is_brcond_inst && brcond_cond_true) begin
        next_PC = PC + bra_pc_inc_value;
    end else if(is_bir_inst) begin
        next_PC = IRQ_latched_PC;
    end else if(irq_sig) begin
        next_PC = 8'h01;
    end else begin
        next_PC = PC + 1;
    end
end

assign extmem_addr = data_reg_rd_a + memop_offset_8;
assign extmem_rd = is_ldmem_inst;
assign extmem_wr = is_stmem_inst;
assign extmem_MOSI = data_reg_rd_b;


endmodule