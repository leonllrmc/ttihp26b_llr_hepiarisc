/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none


module tt_um_llr_hepiarisc (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // All output pins must be assigned. If not used, assign to 0.
  //assign uo_out  = ui_in + uio_in;  // Example: ou_out is the sum of ui_in and uio_in
  assign uio_out[3:0] = 0;
  assign uio_oe[3:0]  = 0;

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, 1'b0};

  wire project_led_red;
  wire project_led_blue;
  wire project_led_green;
  wire project_extflash_spi_cs;
  wire project_extflash_spi_mosi;
  wire project_extflash_spi_miso;
  wire project_extflash_spi_sck;

  assign uo_out[2:0] = {project_extflash_spi_cs, project_extflash_spi_mosi, project_extflash_spi_sck};


  // reg out => {OUT[7:4]}
  // reg in => {IN[7:4]}
  // reg EN => {IO_OUT_EN[7:4]}
  // reg IO out => {IO_OUT[7:4]}
  // reg IO in => {IO_IN[7:4]}


  hepiarisc_top hepiariscTop (
  .CLK(clk),
  .rst_n_ext(rst_n),
  .led_red(project_led_red),
  .led_blue(project_led_blue),
  .led_green(project_led_green),
  .extflash_spi_cs(project_extflash_spi_cs),
  .extflash_spi_mosi(project_extflash_spi_mosi),
  .extflash_spi_miso(ui_in[0]),
  .extflash_spi_sck(project_extflash_spi_sck),

  .gpio_uo(uo_out[7:4]),
  .gpio_ui(ui_in[7:4]),
  .gpio_uio_in(uio_in[7:4]),
  .gpio_uio_out(uio_out[7:4]),
  .gpio_uio_oe(uio_oe[7:4]),


  .irq_ext(ui_in[1]),

  .DEBUG_OUT() // TODO: add proper debug interface (maybe use the SPI fetch cycles to transmit data)
  // 6*8*3 = 18 bytes/cycle = 8 regs + 1 addr + 1 data + 2 curren topcode= 6 left
);

endmodule
  // NOTE: to make compatible with windbond flash = would only need to make addr 24 bit
  typedef enum logic[2:0] {STATE_SPI_RD,
  STATE_SPI_ADDRBANK,
  STATE_SPI_ADDR0, STATE_SPI_ADDR1, // send addr MSB, then LSB
  STATE_SPI_DATA0, STATE_SPI_DATA1, // get data/instruction in [7:0] then [15:8]
  STATE_CPU_EXEC, STATE_MEMOP} exec_state;

module hepiarisc_top (
  input wire CLK,
  input wire rst_n_ext,
  output wire led_red,
  output wire led_blue,
  output wire led_green,
  output reg extflash_spi_cs,
  output wire extflash_spi_mosi,
  input wire extflash_spi_miso,
  output wire extflash_spi_sck,

  output wire [3:0] gpio_uo,
  input wire [3:0] gpio_ui,
  input wire [3:0] gpio_uio_in,
  output wire [3:0] gpio_uio_out,
  output wire [3:0] gpio_uio_oe,


  input wire irq_ext,

  output wire [3:0] DEBUG_OUT
);
wire rst_n = rst_n_ext;

  reg [3:0] GPO_out_reg;
  assign gpio_uo = GPO_out_reg;
  wire [3:0] GPI_in_reg;
  assign GPI_in_reg = gpio_ui;

  reg [3:0] GPIO_out_reg;
  assign gpio_uio_out = GPIO_out_reg;
  reg [3:0] GPIO_oe_reg;
  assign gpio_uio_oe = GPIO_oe_reg;
  wire [3:0] GPIO_in_reg;
  assign GPIO_in_reg = gpio_uio_in;

  
  reg hepiarisc_en;
  wire systick_irq;
  reg [1:0] IRQ_source_en; // IRQ source = 00: none, 01: ext, 10: systick, 11: systick|| ext
  reg [7:0] systick_divider;
  reg systick_reg_reload;

  systick_gen #(
   .min_div(8)
  ) systick_module (
      .clk(CLK),
      .rst_n(rst_n && ~systick_reg_reload),
      .divider(systick_divider),
      .en(hepiarisc_en), // clocks during cpu execution
      .irq_pulse(systick_irq)
   );

  reg irq_ext_old;
  reg irq_ext_buf;
  reg irq_ext_pulse;
  always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
      irq_ext_old <= 1'b0;
      irq_ext_pulse <= 1'b0;
      irq_ext_buf <= 1'b0;
    end else begin
      irq_ext_buf <= irq_ext;
      irq_ext_old <= irq_ext_buf;
      irq_ext_pulse <= irq_ext_buf && ~irq_ext_old;
    end
  end

  reg hepiarisc_irq;
  always_comb begin
    case(IRQ_source_en)
      2'b00: hepiarisc_irq = 1'b0;
      2'b01: hepiarisc_irq = irq_ext_pulse;
      2'b10: hepiarisc_irq = systick_irq;
      2'b11: hepiarisc_irq = irq_ext_pulse || systick_irq;
    endcase
  end
    

  wire SPI_BUSY;
  wire SPI_DONE = ~SPI_BUSY;
  reg [7:0] SPI_DATA_MOSI;
  wire [7:0] SPI_DATA_MISO;

  wire [7:0] hepiarisc_addr;

  reg SPI_SEND_DATA;

  reg SPI_SEND_DATA_PULSE;
  reg SPI_SEND_DATA_OLD;
  reg SPI_DONE_PULSE;
  reg SPI_DONE_OLD;

  always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
      SPI_SEND_DATA_PULSE <= 1'b0;
      SPI_SEND_DATA_OLD <= 1'b0;
    end else begin
      SPI_SEND_DATA_OLD <= SPI_SEND_DATA;
      SPI_SEND_DATA_PULSE <= (~SPI_SEND_DATA_OLD && SPI_SEND_DATA);
     // if(~SPI_SEND_DATA_OLD && SPI_SEND_DATA) begin
     //   SPI_SEND_DATA_PULSE <= 1'b1;
     // end else if(~extflash_spi_cs) begin//SPI_DONE) begin //SPI_DONE_PULSE) begin
     //   SPI_SEND_DATA_PULSE <= 1'b0; 
     // end
    end
  end


  wire hepiarisc_instruction_memop_rd;
  wire hepiarisc_instruction_memop_wr;
  wire hepiarisc_instruction_memop = hepiarisc_instruction_memop_rd || hepiarisc_instruction_memop_wr;
  reg [7:0] hepiarisc_memop_input;
  wire [7:0] hepiarisc_memop_output;
  wire [7:0] hepiarisc_memop_address;

  
  reg [15:0] hepiarisc_instruction;

  hepiarisc cpu(
    .CLK(CLK),
    .rst_n(rst_n),
    .enable(hepiarisc_en),
    
    .instruction_in(hepiarisc_instruction),
    .instruction_addr(hepiarisc_addr),

    .irq(hepiarisc_irq),

    .extmem_MISO(hepiarisc_memop_input),
    .extmem_MOSI(hepiarisc_memop_output),
    .extmem_addr(hepiarisc_memop_address),
    .extmem_wr(hepiarisc_instruction_memop_wr),
    .extmem_rd(hepiarisc_instruction_memop_rd)
  );
  exec_state currentState;

  wire [15:0] flash_addr = {7'h00, hepiarisc_addr, 1'b0};

  // counter peripheral => when divider updated => reset counter
  // could tie rst_n to reg being written maybe (?)

// 64 bytes of ram for now
  reg [7:0] RAM_data [31:0];
  integer ram_idx;


  reg [2:0] reg_rgb;

  always_ff @(posedge CLK or negedge rst_n) begin
    if(~rst_n) begin
      currentState <= STATE_SPI_RD;
      SPI_SEND_DATA <= 1'b0;
      hepiarisc_en <= 1'b0;
      reg_rgb <= 3'b000;

      extflash_spi_cs <= 1'b1;

      for (ram_idx = 0; ram_idx < 64; ram_idx = ram_idx + 1) begin
        RAM_data[ram_idx] <= 8'h00;
      end
    end else begin
    case (currentState)
        STATE_SPI_RD: begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_SPI_ADDRBANK;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= 8'h03; // READ command
            SPI_SEND_DATA <= 1'b1;
            extflash_spi_cs <= 1'b0;
          end
        end

        STATE_SPI_ADDRBANK: begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_SPI_ADDR0;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= 8'h00; // addr[23:16]
            SPI_SEND_DATA <= 1'b1;
          end
        end

        STATE_SPI_ADDR0: begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_SPI_ADDR1;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= flash_addr[15:8]; // addr[15:8] command
            SPI_SEND_DATA <= 1'b1;
          end
        end
 
        STATE_SPI_ADDR1:  begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_SPI_DATA0;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= flash_addr[7:0]; // addr[15:8] command
            SPI_SEND_DATA <= 1'b1;
          end
        end

 
// data are now in big endian
        STATE_SPI_DATA0: begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_SPI_DATA1;
            hepiarisc_instruction[15:8]/*7:0*/ <= SPI_DATA_MISO;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= 8'hFF; // dummy data for read
            SPI_SEND_DATA <= 1'b1;
          end
        end

        STATE_SPI_DATA1: begin
          if(SPI_DONE_PULSE) begin
            currentState <= STATE_CPU_EXEC;
            hepiarisc_instruction[7:0]/*15:8*/ <= SPI_DATA_MISO;
            SPI_SEND_DATA <= 1'b0;
          end else begin
            SPI_DATA_MOSI <= 8'hFF; // dummy data for read
            SPI_SEND_DATA <= 1'b1;
          end
        end

        STATE_CPU_EXEC: begin
          hepiarisc_en <= 1'b1;
          currentState <= STATE_MEMOP;
          extflash_spi_cs <= 1'b1;
        end



        STATE_MEMOP: begin
          systick_reg_reload <= hepiarisc_instruction_memop_wr && (hepiarisc_memop_address[7:1] == 7'b1000100);
          hepiarisc_en <= 1'b0;
          currentState <= STATE_SPI_RD;

            if(hepiarisc_instruction_memop_wr) begin
              if(hepiarisc_memop_address < 32) begin
                RAM_data[hepiarisc_memop_address[4:0]] <= hepiarisc_memop_output;
              end else begin
                case(hepiarisc_memop_address)
                  8'h80: GPO_out_reg <= hepiarisc_memop_output[3:0];
                  // 8'h81: hepiarisc_memop_input <= {4'h0, GPI_in_reg}; -> undefined
                  8'h82: GPIO_out_reg <= hepiarisc_memop_output[3:0];
                  8'h83: GPIO_oe_reg <= hepiarisc_memop_output[3:0];
                  // 8'h84: GPIO_in_reg <= hepiarisc_memop_output[3:0]; -> undefined
                  8'h87: reg_rgb[2:0] <= hepiarisc_memop_output[2:0];
                  // systick
                  8'h88: IRQ_source_en <= hepiarisc_memop_output[1:0];// IRQ source = 00: none, 01: ext, 10: systick, 11: systick|| ext
                  8'h89: systick_divider <= hepiarisc_memop_output;
                endcase
              end
            end else if(hepiarisc_instruction_memop_rd) begin
              if(hepiarisc_memop_address < 32) begin
                hepiarisc_memop_input <= RAM_data[hepiarisc_memop_address[4:0]];
              end else begin
                case(hepiarisc_memop_address)
                  8'h80: hepiarisc_memop_input <= {4'h0, GPO_out_reg};
                  8'h81: hepiarisc_memop_input <= {4'h0, GPI_in_reg};
                  8'h82: hepiarisc_memop_input <= {4'h0, GPIO_out_reg};
                  8'h83: hepiarisc_memop_input <= {4'h0, GPIO_oe_reg};
                  8'h84: hepiarisc_memop_input <= {4'h0, GPIO_in_reg};
                  8'h87: hepiarisc_memop_input <= {5'h00, reg_rgb[2:0]};
                  // systick
                  8'h88: hepiarisc_memop_input <= {6'h00, IRQ_source_en};// IRQ source = 00: none, 01: ext, 10: systick, 11: systick|| ext
                  8'h89: hepiarisc_memop_input <= systick_divider;
                endcase
              end
            end
        end


        default: currentState = STATE_SPI_RD;
    endcase
  end
  end

  wire [2:0] dbg_state = (currentState == STATE_SPI_RD) ? 3'h1 : 
                         (currentState == STATE_SPI_ADDR0) ? 3'h2 : 
                         (currentState == STATE_SPI_ADDR1) ? 3'h3 : 
                         (currentState == STATE_SPI_DATA0) ? 3'h4 : 
                         (currentState == STATE_SPI_DATA1) ? 3'h5 : 
                         (currentState == STATE_CPU_EXEC) ? 3'h6 : 
                         (currentState == STATE_MEMOP) ? 3'h7 : 3'h0;
  assign DEBUG_OUT = {SPI_SEND_DATA_PULSE, reg_rgb};//dbg_state};//{CLK, rst_n, hepiarisc_en, SPI_DONE};

  wire SPI_CLK;
  //clock_divider  #( .DIV_N('d1) ) spi_clk_div ( .clk_in(CLK), .clk_out(SPI_CLK), .do_reset(~rst_n), .is_ready() );

// spi_module 
// #( .SPI_MASTER (1'b1) )
// spi_master
// ( .master_clock(CLK), // 12 MHZ => 1 = OK
// .SCLK_OUT(extflash_spi_sck),
// .SCLK_IN(SPI_CLK), // div by 1 OK for 12 MHz
// .SS_OUT(extflash_spi_cs),
// .SS_IN(),
// .OUTPUT_SIGNAL(extflash_spi_mosi),
// .processing_word(SPI_BUSY), 
// .process_next_word(SPI_SEND_DATA_PULSE),
// .data_word_send(SPI_DATA_MOSI),
// .INPUT_SIGNAL(extflash_spi_miso),
// .data_word_recv(SPI_DATA_MISO),
// .do_reset(~rst_n),
// .is_ready() );

   spi_master #(
    .CLK_DIV(1)   // SCLK = clk / (2*CLK_DIV)
   ) spiMaster (
     .clk(CLK),
     .rst_n(rst_n),   // async, active-low

      .cs_n(),
     .sclk(extflash_spi_sck),
     .mosi(extflash_spi_mosi),
     .miso(extflash_spi_miso),

     .send(SPI_SEND_DATA_PULSE),
     .din(SPI_DATA_MOSI),
     .dout(SPI_DATA_MISO),
    .done(SPI_DONE_PULSE),
    .busy(SPI_BUSY)
);

assign led_green = reg_rgb[0];
assign led_blue = reg_rgb[1];
assign led_red = reg_rgb[2];

endmodule
