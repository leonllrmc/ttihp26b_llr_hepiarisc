module systick_gen #(
   parameter min_div = 8
) (
      input clk,
      input rst_n,
      input [7:0] divider,
      input en, // clocks during cpu execution
      output reg irq_pulse
   );

   localparam counter_width = $clog2(min_div) + 8;

   reg [counter_width-1:0] counter;

   always_ff @(posedge clk or negedge rst_n) begin
      if(~rst_n) begin
         counter <= 0;
         irq_pulse <= 1'b0;
      end else begin
         irq_pulse = 1'b0;

         if(en) begin
            if(counter[counter_width-1:$clog2(min_div)] >= divider) begin
               counter <= 0;
               irq_pulse <= 1'b1;
            end else 
               counter <= counter + 1;
         end
      end
   end
   
endmodule