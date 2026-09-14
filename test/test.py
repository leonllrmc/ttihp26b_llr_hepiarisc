import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Edge, Timer

# ==============================================================================
# 1. SPI Flash Emulator
# ==============================================================================

async def spi_flash_emulator(dut, rom_data, cs_idx=0, sclk_idx=1, mosi_idx=2, miso_idx=0):
    """
    Emulates an external SPI Flash chip (Standard SPI Mode 0, Read Cmd 0x03).
    Listens to `uo_out` for master signals and drives `ui_in` with MISO.
    """
    # Helper functions to extract specific bits from TT I/O busses
    def get_cs():   return (int(dut.uo_out.value) >> cs_idx) & 1 if dut.uo_out.value.is_resolvable else 1
    def get_sclk(): return (int(dut.uo_out.value) >> sclk_idx) & 1 if dut.uo_out.value.is_resolvable else 0
    def get_mosi(): return (int(dut.uo_out.value) >> mosi_idx) & 1 if dut.uo_out.value.is_resolvable else 0
    
    def set_miso(bit):
        try:
            val = int(dut.ui_in.value)
        except ValueError:
            val = 0 # Fallback if ui_in contains 'X' or 'Z'
            
        if bit: val |= (1 << miso_idx)
        else:   val &= ~(1 << miso_idx)
        dut.ui_in.value = val

    state = "CMD"
    shift_reg = 0
    bit_count_rx = 0
    bit_count_tx = 0
    addr = 0
    last_sclk = 0

    dut._log.info("SPI Flash Emulator: Online")

    while True:
        ## Wait for any change on the output pins
        await dut.uo_out.value_change

        #print(dut.uo_out.value.is_resolvable)
        #if dut.uo_out.value.is_resolvable:
        #    print(bin(int(dut.uo_out.value)))
        
        cs = get_cs()
        
        # If Chip Select is high (inactive), reset state
        if cs == 1:
            set_miso(0)
            state = "CMD"
            bit_count_rx = 0
            bit_count_tx = 0
            shift_reg_rx = 0
            shift_reg_tx = 0
            last_sclk = get_sclk()
            continue
            
        sclk = get_sclk()
        
        # --- RISING EDGE (Master drives MOSI, Slave Samples) ---
        if sclk == 1 and last_sclk == 0:
            mosi = get_mosi()
            shift_reg_rx = ((shift_reg_rx << 1) | mosi) & 0xFFFFFFFF
            bit_count_rx += 1

            #print("bcr", bit_count_rx)
            #print(state)

            #print("SCLK rising")
            
            if state == "CMD" and bit_count_rx == 8:
                cmd = shift_reg_rx & 0xFF
                #print("Got cmd", hex(cmd))
                if cmd == 0x03:
                    dut._log.debug("SPI: Standard Read (0x03) received")
                state = "ADDR"
                bit_count_rx = 0
                shift_reg_rx = 0
                
            elif state == "ADDR" and bit_count_rx == 24:
                addr = shift_reg_rx & 0xFFFFFF
                dut._log.debug(f"SPI: Fetching from address 0x{addr:06X}")
                #print(f"SPI: Fetching from address 0x{addr:06X}")
                state = "DATA"
                bit_count_tx = 0
                shift_reg_rx = 0
                
        # --- FALLING EDGE (Slave drives MISO, Master Samples next cycle) ---
        elif sclk == 0 and last_sclk == 1:
            #print("SCLK falling")
            #print("bct", bit_count_tx)
            #print(state)


            if state == "DATA":
                if bit_count_tx % 8 == 0:
                    # Fetch next byte from ROM data
                    if addr < len(rom_data["content"]):
                        #print(f"Loading from addr 0x{addr:06X}")
                        shift_reg_tx = rom_data["content"][addr]
                        #print(f"instruction byte: 0x{shift_reg_tx:02X}")
                    else:
                        shift_reg_tx = 0x00 # Out of bounds returns zero
                    addr += 1
                    
                # Shift out MSB first
                #miso_bit = (shift_reg >> (7 - (bit_count_tx % 8))) & 1
                miso_bit = (shift_reg_tx & 0x80) >> 7
                #print("miso bit", miso_bit)
                #print("0b" + bin(shift_reg_tx)[2:].rjust(8, '0'))
                shift_reg_tx = (shift_reg_tx << 1) & 0xFF
                set_miso(miso_bit)

            bit_count_tx += 1

        last_sclk = sclk

# ==============================================================================
# 2. Helpers
# ==============================================================================

#def words_to_bytes_little_endian(words):
#    """Converts 32-bit RISC-V instructions into a byte array for the SPI Flash."""
#    byte_array = bytearray()
#    for word in words:
#        byte_array.append(word & 0xFF)
#        byte_array.append((word >> 8) & 0xFF)
#        byte_array.append((word >> 16) & 0xFF)
#        byte_array.append((word >> 24) & 0xFF)
#    return byte_array

def ins_array_to_bytearray(ins_array):
    byte_array = bytearray()
    for ins in ins_array:
        byte_array.append((ins >> 8) & 0xFF)
        byte_array.append(ins & 0xFF)
    return byte_array

async def reset_cpu(dut):
    """Applies a standard Tiny Tapeout reset sequence."""
    dut._log.info("Resetting CPU...")
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    
    for _ in range(5):
        await RisingEdge(dut.clk)
        
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    dut._log.info("Reset complete.")

# ==============================================================================
# 3. Main Testbench
# ==============================================================================

@cocotb.test()
async def test_hepiarisc_cpu(dut):
    """Main testbench for the HEPIA RISC-V running from SPI flash."""
    
    # 1. Start the CPU clock (e.g., 50 MHz)
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    rom_bytes = {"content": 0}

    # 2. Define the program (32-bit RISC-V machine code)
    # This will be converted to bytes and served by the SPI emulator.
    dummy_program_words = [
        0x7240,  #R1 = not R1        ; R1 = 0xFF
        0x1488,  #R2 = R2 - R1       ; R2 = 1
        0x0690,  #R3 = R2 + R2       ; R3 = 2
        0x28C0,  #R4 = R3 << 1       ; R4 = 4
        0xB000 # B 0
    ]
    rom_bytes["content"] = ins_array_to_bytearray(dummy_program_words)

    # 3. Start the SPI Flash Emulator concurrently
    # ---> UPDATE THESE INDICES to match your project's info.yaml pin mapping <---
    cocotb.start_soon(spi_flash_emulator(
        dut, 
        rom_data = rom_bytes,
        cs_idx   = 2,  # e.g., uo_out[0]
        sclk_idx = 0,  # e.g., uo_out[1]
        mosi_idx = 1,  # e.g., uo_out[2]
        miso_idx = 0   # e.g., ui_in[0]
    ))


    async def run_test_simple_ALU():
        print("Starting simple ALU program test")
        # 4. Reset the CPU (this triggers the CPU to start its first SPI read)
        await reset_cpu(dut)

        # 5. Let the CPU run and monitor state
        dut._log.info("Starting execution loop...")
        
        max_cycles = 600  # Give it enough cycles to perform SPI transactions
        for cycle in range(max_cycles):
            await RisingEdge(dut.clk)
            
            uo_out_val = int(dut.uo_out.value) if dut.uo_out.value.is_resolvable else 0

            current_ins = dut.user_project.hepiariscTop.cpu.instruction_in
            # Reaching into the Verilog hierarchy to peek at the Program Counter (Optional)
            # ---> UPDATE THIS PATH to match your actual internal module names <---
            try:
                #print(dir(dut.user_project.hepiariscTop.cpu.PC.value))
                pc_val = dut.user_project.hepiariscTop.cpu.PC.value
                #pc_val = "Not Mapped"
            except AttributeError:
                pc_val = "Path Error"

            if dut.user_project.hepiariscTop.hepiarisc_en.value:
                dut._log.info(f"Cycle {cycle:04d} | PC: {pc_val} | uo_out: 0x{uo_out_val:02X} | instruction {hex(int(current_ins))}")
                reg_log_str = ""
                for i in range(8):
                    reg_log_str += f"R{i} : {hex(dut.user_project.hepiariscTop.cpu.regbank.registers[i].value)} | "
                dut._log.info(reg_log_str)
                
            # Optional: Break condition
            # If your RISC-V program writes 0xFF to specific output pins when finished
            # if (uo_out_val & 0xF0) == 0xF0:  
            #     dut._log.info("Program signaled completion.")
            #     break
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[1].value == 0xFF)
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[2].value == 1)
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[3].value == 2)
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[4].value == 4)

        dut._log.info("simple ALU test finished")

    await run_test_simple_ALU()

    dummy_program_words = [
        0x7240,  #R1 = not R1        ; R1 = 0xFF
        0x9117, # jump to bank 1 0x17
        0x8038,   #R0 = 0x38
        0xB000, # B 0, (infloop)
        *[0x0000] * (256-4), # fill
        0x8442, # R2 = 0x42 (fake => if fall on this, PC addr not set properly @ bank jump)  
        0xF003, # false path return bank switch
        *[0x0000] * (0x17-2), # fill
        0x8417, # R2 = 0x17 (true path)
        0xF003, # true path return bank switch
    ]
    rom_bytes["content"] = ins_array_to_bytearray(dummy_program_words)

    print(list(zip(dummy_program_words, range(0, 512))))

    async def run_test_simple_bank_switch():
        print("Starting simple bank switch test")
        # 4. Reset the CPU (this triggers the CPU to start its first SPI read)
        await reset_cpu(dut)

        # 5. Let the CPU run and monitor state
        dut._log.info("Starting execution loop...")
        
        max_cycles = 800  # Give it enough cycles to perform SPI transactions
        for cycle in range(max_cycles):
            await RisingEdge(dut.clk)
            
            uo_out_val = int(dut.uo_out.value) if dut.uo_out.value.is_resolvable else 0

            current_ins = dut.user_project.hepiariscTop.cpu.instruction_in
            # Reaching into the Verilog hierarchy to peek at the Program Counter (Optional)
            # ---> UPDATE THIS PATH to match your actual internal module names <---
            try:
                #print(dir(dut.user_project.hepiariscTop.cpu.PC.value))
                pc_val = dut.user_project.hepiariscTop.cpu.PC.value
                #pc_val = "Not Mapped"
            except AttributeError:
                pc_val = "Path Error"

            hp_bank = dut.user_project.hepiariscTop.cpu.currentBank.value

            if dut.user_project.hepiariscTop.hepiarisc_en.value:
                dut._log.info(f"Cycle {cycle:04d} | bank: {hp_bank} | # PC: {hex(int(pc_val))} | uo_out: 0x{uo_out_val:02X} | instruction {hex(int(current_ins))}")
                dut._log.info(f"return bank: {dut.user_project.hepiariscTop.cpu.returnBank.value} return address {hex(dut.user_project.hepiariscTop.cpu.bankJumpReturnAddr.value)}")
                reg_log_str = ""
                for i in range(8):
                    reg_log_str += f"R{i} : {hex(dut.user_project.hepiariscTop.cpu.regbank.registers[i].value)} | "
                dut._log.info(reg_log_str)
                dut._log.info("")
                
            # Optional: Break condition
            # If your RISC-V program writes 0xFF to specific output pins when finished
            # if (uo_out_val & 0xF0) == 0xF0:  
            #     dut._log.info("Program signaled completion.")
            #     break
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[1].value == 0xFF)
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[0].value == 0x38)
        assert(dut.user_project.hepiariscTop.cpu.regbank.registers[2].value == 0x17)

        dut._log.info("simple bank switch test finished")

    await run_test_simple_bank_switch()