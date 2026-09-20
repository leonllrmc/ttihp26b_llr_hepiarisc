from cocotb.triggers import Timer
from assembler import Program
from common import Clocked, value
from reference import CPU


def unpack_flags(bits): return tuple((bits >> shift) & 1 for shift in (3,2,1,0))
def unpack_regs(bits): return [(bits >> (8*i)) & 255 for i in range(8)]


class Core(Clocked):
    def __init__(self, dut, trace, program: Program):
        super().__init__(dut, trace)
        self.program, self.model = program, CPU()
        self.retired, self.writes = 0, []
        dut.clk.value=0; dut.enable.value=0; dut.irq.value=0
        dut.instruction.value=program.at(0,0).word; dut.miso.value=0
        (trace.directory/(trace.name+".lst")).write_text(program.listing())

    async def reset(self, cycles=3):
        self.dut.enable.value=0; self.dut.irq.value=0
        await super().reset(cycles)
        self.model=CPU();self.retired=0;self.writes=[]
        self.compare("reset")

    def snapshot(self):
        d=self.dut
        return dict(pc=value(d.pc),bank=value(d.bank),regs=unpack_regs(value(d.registers)),
                    flags=unpack_flags(value(d.flags)),sp=value(d.sp))

    def compare(self, context):
        actual=self.snapshot();m=self.model
        expected=dict(pc=m.pc,bank=m.bank,regs=m.regs,flags=m.flags,sp=m.sp)
        mismatches=[]
        if actual!=expected:mismatches.append(f"CPU actual={actual}, expected={expected}")
        stack=[((value(self.dut.stack)>>(12*i+8))&15,(value(self.dut.stack)>>(12*i))&255) for i in range(8)]
        if stack!=m.stack:mismatches.append(f"hardware stack actual={stack}, expected={m.stack}")
        irq=(value(self.dut.irq_bank),value(self.dut.irq_pc),unpack_flags(value(self.dut.irq_flags)))
        if irq!=(m.irq_bank,m.irq_pc,m.irq_flags):mismatches.append(f"IRQ saved context={irq}, expected={(m.irq_bank,m.irq_pc,m.irq_flags)}")
        assert not mismatches, f"{context}: "+"; ".join(mismatches)

    async def step(self, irq=False, enable=True, observe_alu_flags=False):
        ins=self.program.at(self.model.bank,self.model.pc)
        before=self.snapshot()
        self.dut.instruction.value=ins.word
        self.dut.enable.value=int(enable);self.dut.irq.value=int(irq)
        read_data=0
        if ins.mnemonic in ("ld","st"):
            reg,ptr,offset=ins.args
            address=(self.model.regs[ptr]+offset)&255
            read_data=self.model.memory[address]
            self.dut.miso.value=read_data
        await Timer(1,unit="ns")
        assert value(self.dut.rd)==int(ins.mnemonic=="ld"), f"read decode: {ins.source}"
        assert value(self.dut.wr)==int(ins.mnemonic=="st"), f"write decode: {ins.source}"
        if ins.mnemonic in ("ld","st"):
            assert value(self.dut.address)==address, f"address decode: {ins.source}"
            if ins.mnemonic=="st":
                assert value(self.dut.mosi)==self.model.regs[reg], f"write data: {ins.source}"
                if enable:self.writes.append((address,self.model.regs[reg]))
        await self.tick()
        if enable:
            self.model.execute(ins,irq,read_data=read_data)
            self.retired+=1
            # Decoder-isolation tests explicitly use the observed ALU flags as
            # their inputs. Other tests use the independent arithmetic model.
            if observe_alu_flags:self.model.flags=unpack_flags(value(self.dut.flags))
        self.trace.event("instruction", bank=ins.bank,pc=ins.pc,assembly=ins.source,word=f"{ins.word:04x}",
                         enable=enable,irq=irq,before=before,after=self.snapshot(),expected_pc=self.model.pc,
                         expected_bank=self.model.bank,expected_flags=self.model.flags,stack=self.model.stack)
        self.compare(f"{ins.bank:x}:{ins.pc:02x} {ins.source}; irq={irq}, enable={enable}")
        self.dut.enable.value=0;self.dut.irq.value=0

    async def run_to(self,label,limit=300,**kwargs):
        target=self.program.address(label)
        for _ in range(limit):
            if (self.model.bank,self.model.pc)==target:return
            await self.step(**kwargs)
        raise AssertionError(f"CPU did not reach {label} within {limit} instructions")
