from collections import Counter
from assembler import assemble
from common import Clocked,value
from cpu_driver import unpack_regs,unpack_flags
from protocols import SharedSPI,I2CPeer
from reference import timer_period


def firmware(body,handler="bir",extra=""):
    return assemble(f".bank 0\nbra main\n.org 1\nhandler:{handler}\n.org 16\nmain:{body}\n"+extra)


class Monitor:
    def __init__(self,soc):
        self.soc=soc;self.previous=None;self.records=[];self.timer_count=0;self.timer_pulses=0

    def snapshot(self):
        d=self.soc.dut
        return dict(pc=value(d.pc),bank=value(d.bank),enable=value(d.cpu_enable),instruction=value(d.instruction),
            regs=unpack_regs(value(d.registers)),flags=unpack_flags(value(d.flags)),sp=value(d.sp),
            irq=value(d.irq_pending),raw_irq=value(d.irq_raw),state=value(d.state),mem_write=value(d.mem_write),mem_read=value(d.mem_read),
            address=value(d.mem_address),write_data=value(d.mem_write_data),read_data=value(d.mem_read_data),
            gpio_out=(value(d.uio_out)>>4),gpio_oe=(value(d.uio_oe)>>4),gpio_in=value(d.gpio_external),
            reload=value(d.timer_reload),divider=value(d.systick_divider),timer_irq=value(d.systick_irq))

    def sample(self):
        d=self.soc.dut
        if not value(d.rst_n):self.previous=None;self.timer_count=0;return
        after=self.snapshot();before=self.previous
        if self.soc.trace.level=="cycles":self.soc.trace.event("soc_state",**after)
        if before is not None:
            expected_pulse=0
            if before["reload"] or after["reload"]:self.timer_count=0
            elif before["enable"]:
                expected_pulse=int(self.timer_count>=timer_period(before["divider"])-1)
                self.timer_count=0 if expected_pulse else self.timer_count+1
            if self.soc.check_timer:
                assert after["timer_irq"]==expected_pulse,f"MMIO systick: pulse={after['timer_irq']}, expected={expected_pulse}, before={before}, after={after}"
            self.timer_pulses+=after["timer_irq"]
            if after["timer_irq"] or before["reload"]!=after["reload"]:
                self.soc.trace.event("timer",pulse=after["timer_irq"],reload=after["reload"],divider=after["divider"],expected_pulse=expected_pulse)
            if before["enable"]:
                ins=self.soc.program.at(before["bank"],before["pc"])
                assert ins.word==before["instruction"],f"Fetched instruction mismatch at {before['bank']:x}:{before['pc']:02x}"
                record=dict(before=before,after=after,assembly=ins.source,cycle=self.soc.cycles)
                self.records.append(record)
                self.soc.trace.event("instruction",**record)
        self.previous=after


class SoC(Clocked):
    def __init__(self,dut,trace,program,spi_rx=(),i2c_options=None):
        super().__init__(dut,trace)
        dut.clk.value=0;dut.rst_n.value=0;dut.ui_in.value=0;dut.gpio_external.value=0
        dut.slave_scl_low.value=0;dut.slave_sda_low.value=0
        self.program=program;self.check_timer=False
        self.spi=SharedSPI(dut,trace,program.image(),spi_rx)
        self.i2c=I2CPeer(dut,trace,quarter_cycles=125,**(i2c_options or {}))
        self.monitor=Monitor(self);self.peers=[self.spi,self.i2c,self.monitor]
        (trace.directory/(trace.name+".lst")).write_text(program.listing())

    def regs(self):return unpack_regs(value(self.dut.registers))

    async def reset(self,cycles=3):
        await super().reset(cycles)
        assert value(self.dut.i2c_divider)==125,"Full-chip validation must use the production I2C divider (125)"

    async def at(self,label,limit=100000):
        bank,pc=self.program.address(label)
        await self.until(lambda:value(self.dut.bank)==bank and value(self.dut.pc)==pc and value(self.dut.cpu_enable),limit,"instruction "+label)

    async def done(self,limit=300000):
        await self.at("done",limit)
        await self.tick()  # Retire the assembled self-branch, not just its fetch.

    async def irq(self,width=1):
        self.dut.ui_in.value=value(self.dut.ui_in)|2
        await self.tick(width)
        self.dut.ui_in.value=value(self.dut.ui_in)&~2
        await self.tick()

    def memory_events(self,read=None,address=None):
        return [r for r in self.monitor.records if (r["before"]["mem_read"] if read else r["before"]["mem_write"])
                and (address is None or r["before"]["address"]==address)]

    def counts(self):
        return Counter((r["before"]["bank"],r["before"]["pc"]) for r in self.monitor.records)


def poll_i2c(label):
    # r0 is I2C base; r7 is scratch. N/Z are checked separately in the ALU
    # suite. Firmware polls the actual busy register rather than assuming time.
    return f"{label}:ld r7,(r0+5)\nand r7,r7,r7\nbne {label}\n"
