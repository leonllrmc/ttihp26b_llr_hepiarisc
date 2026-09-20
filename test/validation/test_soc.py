import os
import cocotb
from assembler import assemble
from common import Case,Errors,value
from soc_driver import SoC,firmware,poll_i2c

ISR="ldconst r4,1\nadd r6,r6,r4\nnot r5,r5\nbir"


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_boot_flash_all_banks(dut):
    with Case(dut,"soc_boot_flash_all_banks") as c:
        body="".join(f"bnk {bank},worker{bank}\n" for bank in range(16))+"done:bra done"
        extra=""
        for bank in range(16):
            extra+=f".bank {bank}\n.org {128+bank}\nworker{bank}:ldconst r0,0x80\nldconst r1,{bank}\nst r1,(r0)\nbkr\n"
        soc=SoC(dut,c.trace,firmware(body,extra=extra));await soc.reset();await soc.done()
        assert [r["before"]["write_data"] for r in soc.memory_events(address=0x80)]==list(range(16))
        assert {address//512 for address in soc.spi.fetches}==set(range(16))
        assert value(dut.bank)==0 and value(dut.sp)==0


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_ram_all_addresses_and_boundaries(dut):
    with Case(dut,"soc_ram_all_addresses_and_boundaries") as c:
        p=firmware("""ldconst r0,0
         ldconst r1,165
         ldconst r2,176
         ldconst r3,1
         fill:st r1,(r0)
         add r0,r0,r3
         add r1,r1,r3
         add r2,r2,r3
         bne fill
         ldconst r0,0
         ldconst r2,176
         verify:ld r4,(r0)
         not r5,r4
         st r5,(r0)
         ld r6,(r0)
         add r0,r0,r3
         add r2,r2,r3
         bne verify
         ldconst r0,32
         ldconst r1,90
         st r1,(r0-32)
         ld r2,(r0-32)
         ldconst r0,255
         st r1,(r0+1)
         ld r3,(r0+1)
         ldconst r0,80
         st r1,(r0)
         ld r4,(r0)
         ld r5,(r0-1)
         done:bra done""")
        soc=SoC(dut,c.trace,p);await soc.reset();await soc.done()
        reads=soc.memory_events(read=True)
        for i in range(80):
            assert reads[2*i]["before"]["address"]==i
            assert reads[2*i]["before"]["read_data"]==(165+i)&255
            assert reads[2*i+1]["before"]["read_data"]==((165+i)&255)^255
        assert soc.regs()[2:6]==[90,90,0,((165+79)&255)^255]


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_gpio_directions_readback_and_inputs(dut):
    with Case(dut,"soc_gpio_directions_readback_and_inputs") as c:
        p=firmware("""ldconst r0,0x80
          ldconst r1,165
          st r1,(r0)
          ld r6,(r0)
          ldconst r1,0
          ldconst r5,1
          ldconst r6,240
          outer:st r1,(r0+3)
          ldconst r2,0
          ldconst r7,240
          loop:st r2,(r0+2)
          ld r3,(r0+4)
          ld r4,(r0+1)
          add r2,r2,r5
          add r7,r7,r5
          bne loop
          add r1,r1,r5
          add r6,r6,r5
          bne outer
          done:bra done""")
        soc=SoC(dut,c.trace,p);dut.gpio_external.value=10;dut.ui_in.value=0xc0
        await soc.reset();await soc.done()
        assert value(dut.uo_out)>>4==5
        assert soc.memory_events(read=True,address=0x80)[0]["before"]["read_data"]==5
        pads=soc.memory_events(read=True,address=0x84)
        assert len(pads)==256
        for index,record in enumerate(pads):
            mask,data=divmod(index,16)
            expected=(data&mask)|(10&(~mask)&15)
            assert record["before"]["gpio_oe"]==mask
            assert record["before"]["gpio_out"]==data
            assert record["before"]["read_data"]==expected
        assert all(r["before"]["read_data"]==12 for r in soc.memory_events(read=True,address=0x81))
        assert value(dut.uio_oe)&0x0c==0 and value(dut.uio_out)&0x0c==0
        # Exercise all GPO and GPI bit patterns independently of direction.
        for pattern in range(16):
            p=firmware(f"ldconst r0,0x80\nldconst r1,{pattern}\nst r1,(r0)\nld r2,(r0)\nld r3,(r0+1)\ndone:bra done")
            soc=SoC(dut,c.trace,p);dut.ui_in.value=pattern<<4
            await soc.reset();await soc.done()
            assert value(dut.uo_out)>>4==pattern and soc.regs()[2:4]==[pattern,pattern]


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_user_spi_all_bytes_full_duplex(dut):
    with Case(dut,"soc_user_spi_all_bytes_full_duplex") as c:
        responses=[((x*73)^0x96)&255 for x in range(256)]
        p=firmware("""ldconst r0,0x98
          ldconst r1,0
          ldconst r2,1
          loop:st r1,(r0)
          ld r3,(r0+1)
          add r1,r1,r2
          bne loop
          done:bra done""")
        soc=SoC(dut,c.trace,p,spi_rx=responses);await soc.reset();await soc.done()
        assert soc.spi.user_rx==list(range(256))
        assert [r["before"]["read_data"] for r in soc.memory_events(read=True,address=0x99)]==responses
        assert len(soc.spi.frames)>256 and value(dut.uo_out)&8==0


def i2c_program():
    body="ldconst r0,0x90\nldconst r1,0xa0\nst r1,(r0)\n"+poll_i2c("wait_start")
    body+="st r1,(r0+1)\n"+poll_i2c("wait_address")
    body+="ld r2,(r0+7)\nldconst r1,0x55\nst r1,(r0+1)\n"+poll_i2c("wait_data")
    body+="ld r3,(r0+7)\nst r1,(r0)\n"+poll_i2c("wait_restart")
    body+="ldconst r1,0xa1\nst r1,(r0+1)\n"+poll_i2c("wait_read_address")
    body+="ldconst r1,0\nst r1,(r0+2)\nst r1,(r0+3)\n"+poll_i2c("wait_rx1")
    body+="ld r4,(r0+6)\nldconst r1,1\nst r1,(r0+2)\nst r1,(r0+3)\n"+poll_i2c("wait_rx2")
    body+="ld r5,(r0+6)\nst r1,(r0+4)\n"+poll_i2c("wait_stop")+"done:bra done"
    return firmware(body)


def i2c_system_test(stretch):
    async def test(dut):
        with Case(dut,"soc_i2c_mmio_"+("stretch" if stretch else "normal")) as c:
            soc=SoC(dut,c.trace,i2c_program(),i2c_options=dict(read_bytes=[0x96,0x5a],nack_indices={1},stretch=stretch))
            await soc.reset();await soc.done()
            assert soc.i2c.received==[0xa0,0x55,0xa1]
            assert soc.i2c.transmitted==[0x96,0x5a]
            assert soc.regs()[2:6]==[0,1,0x96,0x5a]
            assert [v for who,v in soc.i2c.acks if who=="master"]==[0,1]
            assert soc.i2c.starts==2 and soc.i2c.stops==1
            assert value(dut.scl)==value(dut.sda)==1 and not value(dut.i2c_busy)
            if stretch:assert soc.i2c.stretch_events>=45
    test.__name__="soc_i2c_mmio_"+("stretch" if stretch else "normal");test.__qualname__=test.__name__
    return cocotb.test(timeout_time=30,timeout_unit="ms")(test)


soc_i2c_mmio_normal=i2c_system_test(0)
soc_i2c_mmio_stretch=i2c_system_test(193)


def irq_program(source=1):
    return firmware(f"""ldconst r0,0x88
      ldconst r1,255
      st r1,(r0+1)
      ldconst r1,{source}
      st r1,(r0)
      ldconst r2,1
      work:add r3,r3,r2
      """+"\n".join("add r3,r3,r2" for _ in range(24))+"\nldconst r1,0\nst r1,(r0)\ndone:bra done",ISR)


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_irq_fetch_phase_sweep(dut):
    with Case(dut,"soc_irq_fetch_phase_sweep") as c:
        errors=Errors(c.trace)
        phases=[(state,0) for state in range(8)]+[(5,delay) for delay in (3,10,15,17,19)]
        for state,delay in phases:
            p=irq_program();soc=SoC(dut,c.trace,p);await soc.reset()
            bank,pc=p.address("work")
            await soc.until(lambda:value(dut.pc)==pc and value(dut.state)==state,10000,f"IRQ phase state={state}")
            c.trace.event("check",scenario="IRQ injection phase",state=state,delay=delay)
            await soc.tick(delay);await soc.irq(width=1)
            try:await soc.done(20000)
            except AssertionError as error:
                errors.check("completion",str(error),"done",state=state,delay=delay);continue
            errors.check("ISR executions",soc.regs()[6],1,state=state,delay=delay)
            errors.check("main side effects",soc.regs()[3],25,state=state,delay=delay)
            for address,ins in p.instructions.items():
                if address[0]==0 and pc<=address[1]<pc+25:
                    errors.check("instruction count",soc.counts()[address],1,state=state,delay=delay,assembly=ins.source)
        errors.finish()


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_irq_source_masks_and_held_level(dut):
    with Case(dut,"soc_irq_source_masks_and_held_level") as c:
        for mask in (0,1,2,3):
            p=irq_program(mask);soc=SoC(dut,c.trace,p);await soc.reset()
            target=p.address("work")[1]
            await soc.until(lambda:value(dut.pc)==target and value(dut.state)==2,10000,"masked IRQ injection")
            dut.ui_in.value=value(dut.ui_in)|2
            await soc.done()
            assert soc.regs()[6]==(1 if mask&1 else 0),f"IRQ mask={mask}, count={soc.regs()[6]}"
            assert soc.regs()[3]==25


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_irq_during_user_spi(dut):
    with Case(dut,"soc_irq_during_user_spi") as c:
        p=firmware("""ldconst r0,0x88
          ldconst r1,1
          st r1,(r0)
          ldconst r0,0x98
          ldconst r1,165
          st r1,(r0)
          ld r3,(r0+1)
          """+"\n".join("ldconst r7,0" for _ in range(15))+"\ndone:bra done",ISR)
        soc=SoC(dut,c.trace,p,spi_rx=[0x96]);await soc.reset()
        await soc.until(lambda:value(dut.state)==8,10000,"user SPI waiting state")
        await soc.irq(3);await soc.done()
        assert soc.spi.user_rx==[0xa5] and soc.regs()[3]==0x96 and soc.regs()[6]==1
        assert len(soc.memory_events(address=0x98))==1


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_irq_while_i2c_busy(dut):
    with Case(dut,"soc_irq_while_i2c_busy") as c:
        body="ldconst r0,0x88\nldconst r1,1\nst r1,(r0)\nldconst r0,0x90\nst r1,(r0)\n"+poll_i2c("wait_start")
        body+="ldconst r1,0xa0\nst r1,(r0+1)\n"+poll_i2c("wait_address")
        body+="ldconst r1,0x55\nst r1,(r0+1)\n"+poll_i2c("wait_data")
        body+="st r1,(r0+4)\n"+poll_i2c("wait_stop")+"done:bra done"
        soc=SoC(dut,c.trace,firmware(body,ISR),i2c_options=dict(stretch=193));await soc.reset()
        await soc.until(lambda:len(soc.i2c.received)==1 and value(dut.i2c_busy) and soc.i2c.bits==4,100000,"I2C data bit concurrent IRQ")
        await soc.irq(3);await soc.done()
        assert soc.i2c.received==[0xa0,0x55] and soc.i2c.stops==1
        assert soc.regs()[6]==1


@cocotb.test(timeout_time=30,timeout_unit="ms")
async def soc_systick_mmio_reload_and_interrupts(dut):
    with Case(dut,"soc_systick_mmio_reload_and_interrupts") as c:
        handler="ldconst r4,0x88\nldconst r5,0\nst r5,(r4)\nldconst r5,1\nadd r6,r6,r5\nldconst r5,2\nst r5,(r4)\nbir"
        body="ldconst r0,0x88\nldconst r1,2\nst r1,(r0+1)\nst r1,(r0)\nldconst r2,1\n"
        body+="\n".join("add r3,r3,r2" for _ in range(100))
        body+="\nldconst r1,0\nst r1,(r0)\nld r4,(r0)\nld r5,(r0+1)\ndone:bra done"
        soc=SoC(dut,c.trace,firmware(body,handler));soc.check_timer=True
        await soc.reset();await soc.done()
        assert soc.regs()[3]==100 and soc.regs()[4:6]==[0,2]
        assert soc.regs()[6]>=3 and soc.monitor.timer_pulses>=3
        c.trace.event("check",ISR_count=soc.regs()[6],timer_pulses=soc.monitor.timer_pulses)


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_reset_clears_pending_irq(dut):
    with Case(dut,"soc_reset_clears_pending_irq") as c:
        soc=SoC(dut,c.trace,irq_program());await soc.reset()
        target=soc.program.address("work")[1]
        await soc.until(lambda:value(dut.pc)==target and value(dut.state)==2,10000,"fetch before reset")
        await soc.irq(3)
        await soc.until(lambda:value(dut.irq_pending),50,"latched IRQ")
        dut.rst_n.value=0;await soc.tick(5)
        assert value(dut.irq_pending)==0,"An IRQ from before reset remains pending"
        dut.rst_n.value=1;await soc.done()
        assert soc.regs()[6]==0


@cocotb.test(timeout_time=40,timeout_unit="ms")
async def soc_reset_during_flash_user_spi_and_i2c(dut):
    with Case(dut,"soc_reset_during_flash_user_spi_and_i2c") as c:
        for phase in ("flash","user_spi","i2c"):
            body="ldconst r0,0x98\nldconst r1,165\nst r1,(r0)\nldconst r0,0x90\nst r1,(r0)\n"
            body+=poll_i2c("wait_start")+"ldconst r1,0xa0\nst r1,(r0+1)\n"+poll_i2c("wait_byte")
            body+="st r1,(r0+4)\n"+poll_i2c("wait_stop")+"done:bra done"
            soc=SoC(dut,c.trace,firmware(body),spi_rx=[0x96]*4);await soc.reset()
            predicate={"flash":lambda:value(dut.state)==4,"user_spi":lambda:value(dut.state)==8,
                       "i2c":lambda:value(dut.i2c_busy) and soc.i2c.bits>=3}[phase]
            await soc.until(predicate,100000,"reset phase "+phase)
            dut.rst_n.value=0;await soc.tick(5)
            assert value(dut.uio_oe)&3==0 and value(dut.i2c_busy)==0
            assert value(dut.uo_out)&15==4,"SPI pins must be idle under reset"
            old_starts=soc.i2c.starts
            dut.rst_n.value=1;await soc.tick(5)
            assert not value(dut.i2c_busy) and soc.i2c.starts==old_starts,"Phantom I2C command after reset"
            await soc.done()
            assert value(dut.i2c_busy)==0 and value(dut.scl)==value(dut.sda)==1


def concurrent_test(interrupt):
    async def test(dut):
        with Case(dut,"soc_concurrent_peripherals_"+("irq" if interrupt else "no_irq")) as c:
            body="ldconst r0,0x88\nldconst r1,1\nst r1,(r0)\nldconst r0,0x90\nst r1,(r0)\n"+poll_i2c("wait_start")
            body+="ldconst r1,0xa0\nst r1,(r0+1)\n"+poll_i2c("wait_address")
            body+="ldconst r1,0x55\nst r1,(r0+1)\nldconst r2,0x98\nldconst r1,0xc3\nst r1,(r2)\nld r3,(r2+1)\n"
            body+="ldconst r2,0x80\nldconst r1,11\nst r1,(r2)\n"+poll_i2c("wait_data")
            body+="st r1,(r0+4)\n"+poll_i2c("wait_stop")+"done:bra done"
            soc=SoC(dut,c.trace,firmware(body,ISR),spi_rx=[0x96],i2c_options=dict(stretch=193));await soc.reset()
            await soc.until(lambda:value(dut.state)==8,100000,"overlapping user SPI and I2C")
            assert value(dut.i2c_busy),"Coverage failure: I2C completed before user SPI"
            if interrupt:await soc.irq(3)
            await soc.done()
            assert soc.spi.user_rx==[0xc3] and soc.regs()[3]==0x96
            assert soc.i2c.received==[0xa0,0x55] and soc.i2c.stops==1
            assert value(dut.uo_out)>>4==11 and soc.regs()[6]==int(interrupt)
    test.__name__="soc_concurrent_peripherals_"+("irq" if interrupt else "no_irq");test.__qualname__=test.__name__
    return cocotb.test(timeout_time=30,timeout_unit="ms")(test)


soc_concurrent_peripherals_no_irq=concurrent_test(False)
soc_concurrent_peripherals_irq=concurrent_test(True)


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_simultaneous_timer_external_irq_coalesces(dut):
    with Case(dut,"soc_simultaneous_timer_external_irq_coalesces") as c:
        handler="ldconst r4,0x88\nldconst r5,0\nst r5,(r4)\nldconst r5,1\nadd r6,r6,r5\nbir"
        body="ldconst r0,0x88\nldconst r1,1\nst r1,(r0+1)\nldconst r1,3\nst r1,(r0)\n"
        body+="\n".join("ldconst r7,0" for _ in range(30))+"\ndone:bra done"
        soc=SoC(dut,c.trace,firmware(body,handler));soc.check_timer=True;await soc.reset()
        await soc.until(lambda:value(dut.state)==6 and soc.monitor.timer_count==8 and value(dut.irq_sources)==3,20000,"timer terminal slot")
        dut.ui_in.value=value(dut.ui_in)|2
        await soc.tick(2)
        assert value(dut.systick_irq) and value(dut.irq_external),"Coverage failure: sources were not simultaneous"
        c.trace.event("check",simultaneous_sources=True)
        dut.ui_in.value=value(dut.ui_in)&~2
        await soc.done()
        assert soc.regs()[6]==1,"Two simultaneous sources should produce one pending request"


@cocotb.test(timeout_time=20,timeout_unit="ms")
async def soc_irq_from_bank_restores_flash_fetch(dut):
    with Case(dut,"soc_irq_from_bank_restores_flash_fetch") as c:
        body="ldconst r0,0x88\nldconst r1,1\nst r1,(r0)\nbnk 5,worker\ndone:bra done"
        extra=".bank 5\n.org 128\nworker:ldconst r2,1\nwork:add r3,r3,r2\n"
        extra+="\n".join("add r3,r3,r2" for _ in range(24))+"\nbkr"
        soc=SoC(dut,c.trace,firmware(body,ISR,extra));await soc.reset()
        target=soc.program.address("work")[1]
        await soc.until(lambda:value(dut.bank)==5 and value(dut.pc)==target and value(dut.state)==2,20000,"banked fetch IRQ")
        await soc.irq(3);await soc.done()
        assert soc.regs()[3]==25 and soc.regs()[6]==1 and value(dut.sp)==0
        assert (5*512+2*target) in soc.spi.fetches and 2 in soc.spi.fetches
