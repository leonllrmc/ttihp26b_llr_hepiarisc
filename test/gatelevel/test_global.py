"""Small system regression shared unchanged by RTL and synthesized gates."""
import cocotb
from common import Case, Errors, value
from reference import alu
from pins import Pins, firmware, emit, poll, ISR, IRQ_ENABLE


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def gl_boot_isa_flags(dut):
    with Case(dut,"gl_boot_isa_flags") as c:
        body=""; expected=[]
        vectors=[("add",127,1),("sub",0,1),("lsl",129,0),("lsr",129,0),
                 ("asr",129,0),("and",165,90),("or",165,90),("not",85,0)]
        for i,(op,a,b) in enumerate(vectors):
            args="r3,r1" if op in ("lsl","lsr","asr","not") else "r3,r1,r2"
            body+=f"ldconst r1,{a}\nldconst r2,{b}\n{op} {args}\n"
            result,flags=alu(op,a,b);expected.append(result)
            for j,(flag,pair) in enumerate(zip(flags,[("bnc","bns"),("bzc","bzs"),("bcc","bcs"),("bvc","bvs")])):
                if j==3 and op in ("lsl","lsr","asr"):continue
                body+=f"{pair[flag]} flag_{i}_{j}\nbra error\nflag_{i}_{j}:\n"
            body+="st r3,(r0)\n"
        # Numeric comparisons check the complete ALU -> flags -> branch path.
        for i,(a,b,condition) in enumerate([(0,0,"bgeu"),(0,1,"bltu"),(255,1,"blt"),(127,128,"bgt")]):
            body+=f"ldconst r1,{a}\nldconst r2,{b}\nsub r3,r1,r2\n{condition} cmp_{i}\nbra error\ncmp_{i}:\n"
        body+=emit(0xa5)
        p=Pins(dut,c.trace,firmware(body));await p.reset();await p.finish(expected+[0xa5])
        assert p.checked_fetches[0]==(0,0)


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def gl_ram_all_80_addresses(dut):
    with Case(dut,"gl_ram_all_80_addresses") as c:
        body="""ldconst r7,0
        ldconst r1,165
        ldconst r2,184
        ldconst r3,1
        fill:st r1,(r7)
        add r7,r7,r3
        add r1,r1,r3
        add r2,r2,r3
        bne fill
        ldconst r7,0
        ldconst r2,184
        verify:ld r4,(r7)
        st r4,(r0)
        not r4,r4
        st r4,(r7)
        ld r4,(r7)
        st r4,(r0)
        add r7,r7,r3
        add r2,r2,r3
        bne verify
        ldconst r7,32
        ldconst r1,90
        st r1,(r7-32)
        ld r4,(r7-32)
        st r4,(r0)
        ldconst r7,255
        ld r4,(r7+1)
        st r4,(r0)
        ldconst r7,72
        st r1,(r7)
        ld r4,(r7)
        st r4,(r0)
        """
        expected=[v for i in range(72) for v in ((165+i)&255,((165+i)&255)^255)]+[90,90,0]
        p=Pins(dut,c.trace,firmware(body));await p.reset();await p.finish(expected)


#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_banks_stack_and_register_calls(dut):
#    with Case(dut,"gl_banks_stack_and_register_calls") as c:
#        body="bnk 1,level1\nbnk 0,local\nbnk 15,far\n"+emit(0xa5)
#        extra=".bank 0\n.org 220\nlocal:"+emit(0x20)+"bkr\n"
#        for bank in range(1,9):
#            extra+=f".bank {bank}\n.org 64\nlevel{bank}:"+emit(16+bank)
#            if bank<8:extra+=f"bnk {bank+1},level{bank+1}\n"
#            extra+=emit(128+bank)+"bkr\n"
#        extra+=".bank 15\n.org 255\nfar:bl r2,subroutine\n.org 0\nbkr\n.org 32\nsubroutine:"+emit(0xfe)+"br r2\n"
#        p=Pins(dut,c.trace,firmware(body,extra=extra));await p.reset()
#        await p.finish(list(range(17,25))+list(range(136,128,-1))+[0x20,0xfe,0xa5])
#        assert (15,255) in p.checked_fetches and (15,0) in p.checked_fetches
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_gpio_directions_and_readback(dut):
#    with Case(dut,"gl_gpio_directions_and_readback") as c:
#        body="ldconst r7,0x80\nldconst r1,5\nst r1,(r7)\nld r3,(r7)\nst r3,(r0)\nld r3,(r7+1)\nst r3,(r0)\n"
#        body+="ldconst r1,0\nldconst r2,240\nldconst r6,1\nloop:st r1,(r7+3)\n"
#        for data in (0,15):
#            body+=f"ldconst r4,{data}\nst r4,(r7+2)\n"
#            for address in (2,3,4):body+=f"ld r3,(r7+{address})\nst r3,(r0)\n"
#        body+="add r1,r1,r6\nadd r2,r2,r6\nbne loop\n"
#        expected=[5,10]
#        for mask in range(16):
#            for data in (0,15):expected += [data,mask,(data&mask)|(5&~mask&15)]
#        p=Pins(dut,c.trace,firmware(body));dut.gpio_external.value=5;dut.ui_in.value=0xa0
#        await p.reset();await p.finish(expected)
#        assert value(dut.uo_out)>>4==5 and value(dut.uio_oe)>>4==15
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_user_spi_full_duplex(dut):
#    with Case(dut,"gl_user_spi_full_duplex") as c:
#        body="";expected=[];responses=[]
#        for tx,rx in zip((0,255,85,170,1,128,126,129),(150,105,15,240,128,1,255,0)):
#            body+=emit(tx)+"ld r3,(r0+1)\nst r3,(r0)\n"
#            expected += [tx,rx];responses += [rx,0xff]
#        p=Pins(dut,c.trace,firmware(body),responses);await p.reset();await p.finish(expected)
#        assert len(p.spi.frames)>len(expected),"Flash did not resume between user exchanges"
#
#
#def i2c_firmware():
#    body="ldconst r7,0x90\nst r1,(r7)\n"+poll("start_wait")
#    body+="ldconst r1,0xa0\nst r1,(r7+1)\n"+poll("address_wait")
#    body+="ld r3,(r7+7)\nst r3,(r0)\nldconst r1,0x55\nst r1,(r7+1)\n"+poll("data_wait")
#    body+="ld r3,(r7+7)\nst r3,(r0)\nst r1,(r7)\n"+poll("restart_wait")
#    body+="ldconst r1,0xa1\nst r1,(r7+1)\n"+poll("read_address_wait")
#    for index in range(2):
#        body+=f"ldconst r1,{index}\nst r1,(r7+2)\nst r1,(r7+3)\n"+poll(f"rx_wait{index}")
#        body+="ld r3,(r7+6)\nst r3,(r0)\n"
#    return firmware(body+"st r1,(r7+4)\n"+poll("stop_wait"))
#
#
#def i2c_test(stretch):
#    async def run(dut):
#        with Case(dut,"gl_i2c_"+("stretch" if stretch else "normal")) as c:
#            p=Pins(dut,c.trace,i2c_firmware(),i2c=dict(read_bytes=[0x96,0x5a],nack_indices={1},stretch=stretch))
#            await p.reset();await p.finish([0,1,0x96,0x5a])
#            assert p.i2c.received==[0xa0,0x55,0xa1] and p.i2c.transmitted==[0x96,0x5a]
#            assert [v for who,v in p.i2c.acks if who=="master"]==[0,1]
#            assert p.i2c.starts==2 and p.i2c.stops==1
#            assert value(dut.scl)==value(dut.sda)==1
#            if stretch:assert p.i2c.stretch_events>=45
#    run.__name__="gl_i2c_"+("stretch" if stretch else "normal");run.__qualname__=run.__name__
#    return cocotb.test(timeout_time=20,timeout_unit="ms")(run)
#
#
#gl_i2c_normal=i2c_test(0)
#gl_i2c_stretch=i2c_test(193)
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_external_irq_banked_resume(dut):
#    with Case(dut,"gl_external_irq_banked_resume") as c:
#        for enabled in (0,1):
#            body="ldconst r7,0x88\nldconst r1,"+str(enabled)+"\nst r1,(r7)\nbnk 5,worker\nst r3,(r0)\nst r6,(r0)\n"
#            extra=".bank 5\n.org 64\nworker:ldconst r1,127\nldconst r2,1\nsubject:add r3,r1,r2\nbvs correct\nbra error5\ncorrect:bkr\nerror5:bra error5"
#            p=Pins(dut,c.trace,firmware(body,ISR,extra),scenario=f"enabled{enabled}");await p.reset();await p.fetch("subject")
#            # Hold high through the rest of the program: exactly one rising edge.
#            dut.ui_in.value=value(dut.ui_in)|2
#            await p.finish(([0xe1] if enabled else [])+[128,enabled])
#            assert p.checked_fetches.count((0,1))==enabled
#
#
#@cocotb.test(timeout_time=30, timeout_unit="ms")
#async def gl_irq_controlflow_and_stack(dut):
#    with Case(dut,"gl_irq_controlflow_and_stack") as c:
#        for kind in ("branch","call","return","bank_call","bank_return","bir"):
#            extra=""
#            if kind=="bank_return":
#                body=IRQ_ENABLE+"bnk 3,subject\n"+emit(0xc3)+"st r6,(r0)\n"
#                extra=".bank 3\n.org 64\nsubject:bkr\n"
#            elif kind=="bir":
#                body=IRQ_ENABLE+"bnk 3,worker\n"+emit(0xc3)+"st r6,(r0)\n"
#                extra=".bank 3\n.org 64\nworker:ldconst r1,127\nldconst r2,1\nsubject:add r3,r1,r2\nbvs correct3\nbra error3\ncorrect3:bkr\nerror3:bra error3\n"
#            else:
#                op={"branch":"bra destination","call":"bl r2,destination","return":"br r2","bank_call":"bnk 3,worker"}[kind]
#                body=IRQ_ENABLE+f"ldconst r2,destination\nsubject:{op}\nbra destination\n.org 96\ndestination:"+emit(0xc3)+"st r6,(r0)\n"
#                if kind=="bank_call":extra=".bank 3\n.org 64\nworker:bkr\n"
#            handler=ISR.replace("bir","irq_return:bir")
#            p=Pins(dut,c.trace,firmware(body,handler,extra),scenario=kind);await p.reset();await p.fetch("subject");await p.irq()
#            if kind=="bir":await p.fetch("irq_return");await p.irq()
#            await p.finish([0xe1]*(2 if kind=="bir" else 1)+[0xc3,2 if kind=="bir" else 1])
#
#
#@cocotb.test(timeout_time=30, timeout_unit="ms")
#async def gl_irq_pin_phase_sweep(dut):
#    print("Skipping test")
#    return None
#    with Case(dut,"gl_irq_pin_phase_sweep") as c:
#        errors=Errors(c.trace)
#        body=IRQ_ENABLE+"ldconst r2,1\nsubject:"+"\n".join(["add r3,r3,r2"]*25)+"\nst r3,(r0)\nst r6,(r0)\n"
#        # Every clock near the end of the instruction frame, including odd
#        # offsets: sampling only every other clock can miss one-cycle races.
#        for delay in (0,16,24,*range(28,49)):
#            p=Pins(dut,c.trace,firmware(body,ISR),scenario=f"delay{delay}");await p.reset();await p.fetch("subject")
#            await p.tick(delay);await p.irq(width=1)
#            try:await p.finish([0xe1,25,1],limit=20000)
#            except AssertionError as error:errors.check("IRQ phase",str(error),"signature [225,25,1]",delay=delay)
#        errors.finish()
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_systick_instruction_counter(dut):
#    print("Skipping test")
#    return None
#    with Case(dut,"gl_systick_instruction_counter") as c:
#        body="ldconst r7,0x88\nldconst r1,255\nst r1,(r7+1)\nldconst r1,0\nst r1,(r7)\nldconst r2,0\n"
#        body+="ld r3,(r7+2)\nst r3,(r0)\n"*17
#        # Reading each counter sample and sending it are two executed slots.
#        # SPI stalls must not advance an instruction-based timer.
#        body+="st r1,(r7+1)\nldconst r2,0\nld r3,(r7+2)\nst r3,(r0)\n"
#        # Divider one wraps after nine executed slots (8*divider+1), even
#        # though a user SPI exchange adds many wall-clock cycles between reads.
#        body+="ldconst r1,1\nst r1,(r7+1)\nldconst r2,0\n"
#        body+="ld r3,(r7+2)\nst r3,(r0)\n"*18
#        p=Pins(dut,c.trace,firmware(body));await p.reset()
#        await p.finish([i//4 for i in range(17)]+[0]+[((2*i)%9)//8 for i in range(18)])
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_systick_interrupt_and_mask(dut):
#    print("Skipping test")
#    return None
#    with Case(dut,"gl_systick_interrupt_and_mask") as c:
#        handler="ldconst r7,0x88\nldconst r4,0\nst r4,(r7)\nldconst r4,1\nadd r6,r6,r4\nbir"
#        body="ldconst r7,0x88\nldconst r1,2\nst r1,(r7+1)\nst r1,(r7)\nldconst r2,1\n"
#        body+="\n".join(["add r3,r3,r2"]*60)+"\nst r3,(r0)\nst r6,(r0)\nld r4,(r7)\nst r4,(r0)\n"
#        p=Pins(dut,c.trace,firmware(body,handler));await p.reset();await p.finish([60,1,0],limit=30000)
#
#
#@cocotb.test(timeout_time=20, timeout_unit="ms")
#async def gl_concurrent_i2c_spi_gpio_irq(dut):
#    with Case(dut,"gl_concurrent_i2c_spi_gpio_irq") as c:
#        body=IRQ_ENABLE+"ldconst r7,0x90\nst r1,(r7)\n"+poll("start_wait")
#        body+="ldconst r1,0xa0\nst r1,(r7+1)\n"+poll("addr_wait")
#        body+="ldconst r1,0x55\nst r1,(r7+1)\n"+emit(0xc3)+"ld r3,(r0+1)\nst r3,(r0)\n"
#        body+="ldconst r2,0x80\nldconst r1,11\nst r1,(r2)\n"+poll("data_wait")
#        body+="st r1,(r7+4)\n"+poll("stop_wait")+"st r6,(r0)\n"
#        p=Pins(dut,c.trace,firmware(body,"ldconst r4,1\nadd r6,r6,r4\nbir"),responses=[0x96],i2c=dict(stretch=193))
#        await p.reset();await p.until(lambda:bool(value(dut.uo_out)&8),reason="user SPI edge")
#        assert p.i2c.active and len(p.i2c.received)==1 and p.i2c.bits<9,"Transfers did not overlap"
#        await p.irq();await p.finish([0xc3,0x96,1])
#        assert p.i2c.received==[0xa0,0x55] and p.i2c.stops==1 and value(dut.uo_out)>>4==11
#
#
#@cocotb.test(timeout_time=30, timeout_unit="ms")
#async def gl_reset_active_buses_and_pending_irq(dut):
#    with Case(dut,"gl_reset_active_buses_and_pending_irq") as c:
#        body=IRQ_ENABLE+"hazard:ldconst r1,165\nst r1,(r0)\nldconst r7,0x90\nst r1,(r7)\n"+poll("start_wait")
#        body+="ldconst r1,0xa0\nst r1,(r7+1)\n"+poll("byte_wait")+"st r1,(r7+4)\n"+poll("stop_wait")
#        recovery="ldconst r7,0\nld r3,(r7)\nst r3,(r0)\nldconst r7,79\nld r3,(r7)\nst r3,(r0)\n"+emit(0x5a)+"st r6,(r0)\n"
#        for phase in ("flash","user_spi","i2c","pending_irq"):
#            p=Pins(dut,c.trace,firmware(body,ISR),scenario=phase+"_before");await p.reset()
#            if phase in ("flash","pending_irq"):
#                await p.fetch("hazard")
#                if phase=="pending_irq":await p.irq()
#            elif phase=="user_spi":await p.until(lambda:bool(value(dut.uo_out)&8),reason="SPI reset phase")
#            else:await p.until(lambda:p.i2c.active and p.i2c.bits>=3,reason="I2C reset phase")
#            # Replace only the external flash/slave models while hardware reset
#            # is asserted. No internal state is read or forced.
#            p=Pins(dut,c.trace,firmware(recovery,ISR),scenario=phase+"_recovery")
#            await p.reset();await p.finish([0,0,0x5a,0])
#            assert not p.i2c.starts and not p.i2c.stops
