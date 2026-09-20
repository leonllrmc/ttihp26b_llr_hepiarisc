import cocotb
from common import Case,Clocked,value
from reference import timer_period


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def systick_dividers_and_sparse_enable(dut):
    with Case(dut,"systick_dividers_and_sparse_enable") as c:
        clock=Clocked(dut,c.trace);dut.en.value=0;dut.divider.value=0
        for divider in (0,1,2,7,31,127,255):
            dut.en.value=0;dut.divider.value=divider;await clock.reset()
            counter=pulses=enabled=0
            period=timer_period(divider)
            latched_irq = 0
            for _ in range(3*period*3):
                en=int(c.rng.random()<0.7);dut.en.value=en
                expected=int(((not en) and latched_irq) or (en and counter>=period-1))
                if en: latched_irq = expected
                if en:counter=0 if expected else counter+1
                if (en and counter>=period): counter = 0
                enabled+=en
                await clock.tick()
                actual=value(dut.irq_pulse);pulses+=actual
                c.trace.event("timer",divider=divider,en=en,enabled=enabled,sim_counter=counter,counter_value=int(dut.systick_counter_out.value),pulse=actual,expected=expected)
                assert actual==expected,f"divider={divider}, enabled={enabled}, counter_value={dut.systick_counter_out}, pulse={actual}, expected={expected}"
            assert pulses>=2


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def systick_pause_reset_and_divider_change(dut):
    with Case(dut,"systick_pause_reset_and_divider_change") as c:
        clock=Clocked(dut,c.trace);dut.en.value=0;dut.divider.value=7;await clock.reset()
        counter=0;divider=7
        for cycle in range(1800):
            if cycle in (30,120,400,800):
                divider={30:1,120:0,400:255,800:2}[cycle];dut.divider.value=divider
            reset=cycle in (70,71,72,600)
            en=cycle%13 not in (3,4,5,6)
            dut.rst_n.value=int(not reset);dut.en.value=int(en)
            expected=(not en) and latched_irq
            if reset:counter=0
            elif en:
                expected=int((en and counter>=timer_period(divider)-1))
                latched_irq = expected
                counter=0 if expected else counter+1
            await clock.tick()
            c.trace.event("timer",cycle=cycle,divider=divider,en=en,reset=reset,expected=expected,pulse=value(dut.irq_pulse))
            assert value(dut.irq_pulse)==expected
