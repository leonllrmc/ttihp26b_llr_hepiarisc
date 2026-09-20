"""Gate-level-compatible package peers and firmware signatures.

Flash transactions show FETCHES, never claimed instruction retirement. All
architectural assertions are made by firmware and/or observable output bytes.
"""
import json
import os
from cocotb.triggers import Timer
from assembler import assemble
from common import value
from protocols import SharedSPI, I2CPeer


def firmware(body, handler="bir", extra=""):
    return assemble("bra main\n.org 1\nhandler:"+handler+
                    "\n.org 32\nmain:ldconst r0,0x98\n"+body+
                    "\ndone:bra done\nerror:bra error\n"+extra)


def emit(*data):
    return "".join(f"ldconst r1,{x}\nst r1,(r0)\n" for x in data)


def poll(label):
    return f"{label}:ld r5,(r7+5)\nand r5,r5,r5\nbne {label}\n"


ISR = "ldconst r4,1\nadd r6,r6,r4\nldconst r4,0xe1\nst r4,(r0)\nbir"
IRQ_ENABLE = "ldconst r7,0x88\nldconst r1,1\nst r1,(r7)\n"


class Pins:
    def __init__(self, dut, trace, program, responses=(), i2c=None, scenario="main"):
        self.dut, self.trace, self.program = dut, trace, program
        self.period = float(os.getenv("HEPIA_GL_CLOCK_NS", "10"))
        self.cycles = 0
        self.scenario = scenario
        dut.clk.value=0; dut.rst_n.value=0; dut.ui_in.value=0
        dut.gpio_external.value=0; dut.slave_scl_low.value=0; dut.slave_sda_low.value=0
        self.spi = SharedSPI(dut, trace, program.image(), responses)
        self.i2c = I2CPeer(dut, trace, quarter_cycles=int(os.getenv("HEPIA_GL_I2C_DIV", "125")),
                           clock_period_ns=self.period, **(i2c or {}))
        self.seen_fetches=0
        self.checked_fetches=[]
        if not hasattr(trace,"observations"):trace.observations=[]
        (trace.directory/(trace.name+"-"+scenario+".lst")).write_text(program.listing())
        trace.event("check", scenario=scenario, clock_ns=self.period, mode=os.getenv("HEPIA_GL_MODE"))

    async def tick(self, count=1):
        for _ in range(count):
            self.dut.clk.value=0
            await Timer(self.period/2,unit="ns")
            self.dut.clk.value=1
            await Timer(self.period/10,unit="ns")
            self.cycles+=1
            # Fail on unresolved package outputs even when the SPI peer is idle.
            outputs={key:value(getattr(self.dut,key)) for key in ("uo_out","uio_out","uio_oe")}
            assert outputs["uio_oe"]&12==0, "Reserved I/O pins drive the bus"
            assert outputs["uio_out"]&outputs["uio_oe"]&3==0, "I2C drives high"
            self.spi.sample(); self.i2c.sample()
            if self.trace.level=="cycles":
                self.trace.event("pins", cycle=self.cycles, rst_n=value(self.dut.rst_n),
                                 ui_in=value(self.dut.ui_in), **outputs)
            for address in self.spi.fetches[self.seen_fetches:]:
                bank,pc=divmod(address//2,256)
                ins=self.program.at(bank,pc)
                self.checked_fetches.append((bank,pc))
                self.trace.event("check", observation="flash_fetch", bank=bank, pc=pc, assembly=ins.source)
                assert (bank,pc)!=self.program.address("error"), f"Firmware assertion failed; fetch {bank:x}:{pc:02x}"
            self.seen_fetches=len(self.spi.fetches)
            await Timer(self.period*0.4,unit="ns")

    async def reset(self):
        self.dut.rst_n.value=0
        await self.tick(8)
        assert value(self.dut.uo_out)==4, "Reset did not establish idle SPI/GPO"
        assert value(self.dut.uio_oe)==0, "Reset did not release GPIO/I2C"
        self.dut.rst_n.value=1
        await self.tick(2)

    async def until(self, predicate, limit=500000, reason="completion"):
        for _ in range(limit):
            if predicate():return
            await self.tick()
        raise AssertionError(f"Timeout after {limit} clocks: {reason}; last fetches {self.checked_fetches[-12:]}; SPI={self.spi.user_rx[-24:]}")

    async def fetch(self,label,after=0):
        target=self.program.address(label)
        await self.until(lambda:target in self.checked_fetches[after:],reason="fetch "+label)

    async def irq(self,width=4):
        self.dut.ui_in.value=value(self.dut.ui_in)|2
        self.trace.event("check", stimulus="external IRQ rising", cycle=self.cycles)
        await self.tick(width)
        self.dut.ui_in.value=value(self.dut.ui_in)&~2
        await self.tick()

    async def finish(self, expected, limit=500000):
        target=self.program.address("done")
        await self.until(lambda:self.checked_fetches.count(target)>=3,limit,"stable done loop")
        assert self.spi.user_rx==list(expected), f"SPI signature {self.spi.user_rx} != {list(expected)}"
        result=dict(scenario=self.scenario, spi_tx=self.spi.user_rx, spi_rx=self.spi.user_tx,
                    i2c_tx=self.i2c.received, i2c_rx=self.i2c.transmitted, i2c_acks=self.i2c.acks,
                    i2c_starts=self.i2c.starts, i2c_stops=self.i2c.stops,
                    gpo=value(self.dut.uo_out)>>4, gpio_oe=value(self.dut.uio_oe)>>4,
                    fetches=self.checked_fetches)
        self.trace.observations.append(result)
        self.trace.event("check", signature=result)
        (self.trace.directory/(self.trace.name+".observations.json")).write_text(json.dumps(self.trace.observations,indent=2))
