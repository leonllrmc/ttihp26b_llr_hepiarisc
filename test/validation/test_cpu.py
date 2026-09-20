import os
import cocotb
from assembler import assemble, ALU, CONDITIONS
from common import Case, value
from cpu_driver import Core
from reference import condition, signed8


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def cpu_immediates_registers_and_enable(dut):
    with Case(dut,"cpu_immediates_registers_and_enable") as c:
        for reg in range(8):
            for data in range(256):
                p=assemble(f"ldconst r{reg},{data}\ndone:bra done")
                core=Core(dut,c.trace,p);await core.reset()
                await core.step(enable=False,irq=True)
                await core.step(enable=False)
                await core.step()
                assert core.model.regs[reg]==data


def make_alu_test(op):
    async def test(dut):
        with Case(dut,"cpu_register_decode_"+op) as c:
            for rd in range(8):
                for ra in range(8):
                    for rb in range(8):
                        a,b=c.rng.randrange(256),c.rng.randrange(256)
                        operation=f"{op} r{rd},r{ra}"+(f",r{rb}" if op not in ("lsl","lsr","asr","not") else "")
                        p=assemble(f"ldconst r{ra},{a}\nldconst r{rb},{b}\n{operation}\ndone:bra done")
                        core=Core(dut,c.trace,p);await core.reset();await core.run_to("done")
    test.__name__="cpu_register_decode_"+op
    test.__qualname__=test.__name__
    return cocotb.test(timeout_time=5,timeout_unit="ms")(test)


for operation in ALU: globals()["cpu_register_decode_"+operation]=make_alu_test(operation)


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def cpu_conditions_decode_and_reserved(dut):
    with Case(dut,"cpu_conditions_decode_and_reserved") as c:
        reached=set()
        for code in range(16):
            for a in (0,1,63,127,128,255):
                for b in (0,1,63,127,128,255):
                    p=assemble(f"""ldconst r1,{a}
                      ldconst r2,{b}
                      sub r3,r1,r2
                      brcond {code},taken
                      ldconst r0,0
                      bra done
                      taken:ldconst r0,1
                      done:bra done""")
                    core=Core(dut,c.trace,p);await core.reset()
                    await core.step();await core.step();await core.step(observe_alu_flags=True)
                    expected=int(condition(code,core.model.flags));reached.add((code,expected))
                    await core.run_to("done")
                    assert core.model.regs[0]==expected
        for code in range(14):assert (code,0) in reached and (code,1) in reached, f"condition {code} lacks both outcomes"
        assert (14,1) not in reached and (15,1) not in reached
        c.trace.event("check",condition_outcomes=sorted(reached))


def comparison_test(name,predicate):
    async def test(dut):
        with Case(dut,"cpu_compare_"+name) as c:
            for a in (0,1,2,63,127,128,254,255):
                for b in (0,1,2,63,127,128,254,255):
                    p=assemble(f"""ldconst r1,{a}
                      ldconst r2,{b}
                      sub r3,r1,r2
                      {name} taken
                      ldconst r0,0
                      bra done
                      taken:ldconst r0,1
                      done:bra done""")
                    core=Core(dut,c.trace,p);await core.reset()
                    # Do not stop at an ALU flag discrepancy: test the actual
                    # taken/not-taken decision against numeric comparison.
                    await core.step();await core.step();await core.step(observe_alu_flags=True)
                    await core.run_to("done")
                    assert core.model.regs[0]==int(predicate(a,b)), f"{name}: a={a}, b={b}, flags={core.model.flags}"
    test.__name__="cpu_compare_"+name
    test.__qualname__=test.__name__
    return cocotb.test(timeout_time=5,timeout_unit="ms")(test)


for mnemonic,predicate in {
 "bgeu":lambda a,b:a>=b,"bltu":lambda a,b:a<b,"bgtu":lambda a,b:a>b,"bleu":lambda a,b:a<=b,
 "bge":lambda a,b:signed8(a)>=signed8(b),"blt":lambda a,b:signed8(a)<signed8(b),
 "bgt":lambda a,b:signed8(a)>signed8(b),"ble":lambda a,b:signed8(a)<=signed8(b),
 "beq":lambda a,b:a==b,"bne":lambda a,b:a!=b}.items():
    globals()["cpu_compare_"+mnemonic]=comparison_test(mnemonic,predicate)


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def cpu_memory_signed_displacements_aliasing(dut):
    with Case(dut,"cpu_memory_signed_displacements_aliasing") as c:
        for base in (0,1,31,32,79,80,127,128,224,255):
            for offset in range(-32,32):
                data=c.rng.randrange(256)
                p=assemble(f"""ldconst r1,{base}
                    ldconst r2,{data}
                    st r2,(r1+{offset})
                    ld r3,(r1+{offset})
                    ld r1,(r1+{offset})
                    done:bra done""")
                core=Core(dut,c.trace,p);await core.reset();await core.run_to("done")
                assert core.model.regs[1]==core.model.regs[3]==data
                assert core.writes==[((base+offset)&255,data)]


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_pc_wrap_calls_and_flag_preservation(dut):
    with Case(dut,"cpu_pc_wrap_calls_and_flag_preservation") as c:
        p=assemble("""bra main
        .org 16
        main:ldconst r1,127
        ldconst r2,1
        add r3,r1,r2
        ldconst r0,20
        st r3,(r0)
        ld r4,(r0)
        bl r7,subroutine
        bnk 3,bankworker
        done:bra done
        subroutine:ldconst r5,42
        br r7
        .bank 3
        .org 255
        bankworker:ldconst r6,21
        .org 0
        bkr""")
        core=Core(dut,c.trace,p);await core.reset();await core.run_to("done")
        assert core.model.flags==(1,0,0,1)
        assert core.model.regs[4:7]==[128,42,21]
        # BL at the final word must save return address zero.
        p=assemble("bra callsite\n.org 16\nworker:br r7\n.org 255\ncallsite:bl r7,worker")
        core=Core(dut,c.trace,p);await core.reset()
        await core.step();await core.step();assert core.model.regs[7]==0
        await core.step();assert core.model.pc==0


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_bank_all_destinations_and_same_bank(dut):
    with Case(dut,"cpu_bank_all_destinations_and_same_bank") as c:
        for bank in range(16):
            p=assemble(f"""bnk {bank},worker
             done:bra done
             .bank {bank}
             .org 64
             worker:ldconst r2,{bank}
             bl r7,localcall
             bkr
             localcall:ldconst r3,42
             br r7""")
            core=Core(dut,c.trace,p);await core.reset();await core.run_to("done")
            assert core.model.regs[2:4]==[bank,42]


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_bank_stack_eight_frames_and_reuse(dut):
    with Case(dut,"cpu_bank_stack_eight_frames_and_reuse") as c:
        source="bnk 1,worker1\nbnk 1,worker1\ndone:bra done\n"
        for bank in range(1,9):
            source+=f".bank {bank}\n.org 32\nworker{bank}:ldconst r0,{bank}\n"
            if bank<8:source+=f"bnk {bank+1},worker{bank+1}\n"
            source+="bkr\n"
        core=Core(dut,c.trace,assemble(source));await core.reset();await core.run_to("done")
        assert core.model.sp==0 and core.model.bank==0 and core.model.regs[0]==8


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_bank_stack_wrap_characterization(dut):
    with Case(dut,"cpu_bank_stack_wrap_characterization") as c:
        source="bnk 1,worker1\ndone:bra done\n"
        for bank in range(1,10):
            source+=f".bank {bank}\nworker{bank}:"
            source+=(f"bnk {bank+1},worker{bank+1}\n" if bank<9 else "ldconst r0,9\n")
            source+="bkr\n"
        core=Core(dut,c.trace,assemble(source));await core.reset()
        for _ in range(10):await core.step()
        assert core.model.sp==1
        for _ in range(9):await core.step()
        c.trace.event("check",classification="unprotected circular stack; overflow loses oldest frame",state=core.snapshot())
        # Empty stack return is deterministic after reset, but not a valid call.
        core=Core(dut,c.trace,assemble("bkr"));await core.reset();await core.step()
        assert core.model.pc==0 and core.model.sp==7


IRQ_PREFIX="""bra main
 .org 1
 handler:ldconst r4,1
 add r6,r6,r4
 not r5,r5
 irq_return:bir
 .org 16
 main:ldconst r0,32
 ldconst r1,1
 ldconst r2,128
 ldconst r7,destination
 """


def irq_test(kind):
    async def test(dut):
        with Case(dut,"cpu_irq_"+kind) as c:
            extra=""
            if kind=="bank_return":
                body="bnk 2,subject\ndestination:bra destination\n.bank 2\n.org 64\nsubject:bkr"
            elif kind=="banked_alu":
                body="bnk 2,worker\ndestination:bra destination\n.bank 2\n.org 64\nworker:ldconst r3,0\nsubject:add r3,r3,r1\nbkr"
            else:
                op={"add":"add r3,r1,r2","ldconst":"ldconst r3,42","load":"ld r3,(r0)",
                    "store":"st r2,(r0)","branch":"bra destination","call":"bl r7,destination",
                    "return":"br r7","condition_taken":"bvc destination",
                    "condition_not_taken":"bvs destination","bank_call":"bnk 2,worker"}[kind]
                body=f"subject:{op}\nbra destination\n.org 96\ndestination:bra destination"
                if kind=="bank_call":extra="\n.bank 2\n.org 64\nworker:ldconst r3,42\nbkr"
            p=assemble(IRQ_PREFIX+body+extra)
            core=Core(dut,c.trace,p);await core.reset();await core.run_to("subject")
            await core.step(irq=True)
            continuation=(core.model.irq_bank,core.model.irq_pc)
            assert (core.model.bank,core.model.pc)==(0,1)
            await core.run_to("irq_return");await core.step()
            assert (core.model.bank,core.model.pc)==continuation
            assert core.model.regs[6]==1
            await core.run_to("destination")
            if kind=="store":assert core.writes==[(32,128)]
    test.__name__="cpu_irq_"+kind
    test.__qualname__=test.__name__
    return cocotb.test(timeout_time=1,timeout_unit="ms")(test)


for kind in ("add","ldconst","load","store","branch","call","return","condition_taken","condition_not_taken","bank_call","bank_return","banked_alu"):
    globals()["cpu_irq_"+kind]=irq_test(kind)


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_irq_on_bir(dut):
    with Case(dut,"cpu_irq_on_bir") as c:
        # Make both the continuation bank and flags differ from the handler's,
        # so a new IRQ on BIR must save the restored context, not the ISR state.
        prefix=IRQ_PREFIX.replace("not r5,r5","and r5,r4,r4")
        p=assemble(prefix+"bnk 2,subject\ndestination:bra destination\n.bank 2\n.org 64\nsubject:add r3,r1,r2\nbkr")
        core=Core(dut,c.trace,p);await core.reset();await core.run_to("subject");await core.step(irq=True)
        continuation=(core.model.irq_bank,core.model.irq_pc,core.model.irq_flags)
        await core.run_to("irq_return");await core.step(irq=True)
        assert (core.model.irq_bank,core.model.irq_pc,core.model.irq_flags)==continuation
        await core.run_to("irq_return");await core.step();await core.run_to("destination")
        assert core.model.regs[6]==2


@cocotb.test(timeout_time=5,timeout_unit="ms")
async def cpu_seeded_mixed_programs(dut):
    with Case(dut,"cpu_seeded_mixed_programs") as c:
        for trial in range(40 if os.getenv("HEPIA_STRESS")=="1" else 6):
            source="\n".join(f"ldconst r{r},{c.rng.randrange(256)}" for r in range(8))+"\n"
            for _ in range(180):
                op=c.rng.choice(list(ALU)+["ldconst","ld","st"])
                rd,ra,rb=[c.rng.randrange(8) for _ in range(3)]
                if op=="ldconst":line=f"ldconst r{rd},{c.rng.randrange(256)}"
                elif op in ("ld","st"):line=f"{op} r{rd},(r{ra}+{c.rng.randrange(-32,32)})"
                elif op in ("lsl","lsr","asr","not"):line=f"{op} r{rd},r{ra}"
                else:line=f"{op} r{rd},r{ra},r{rb}"
                source+=line+"\n"
            source+="done:bra done"
            core=Core(dut,c.trace,assemble(source));await core.reset();await core.run_to("done")
            c.trace.event("check",trial=trial,retired=core.retired)


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_irq_pc_wrap_and_disable_side_effects(dut):
    with Case(dut,"cpu_irq_pc_wrap_and_disable_side_effects") as c:
        p=assemble("bra subject\n.org 1\nhandler:not r5,r5\nbir\n.org 255\nsubject:add r0,r0,r0")
        core=Core(dut,c.trace,p);await core.reset();await core.step()
        await core.step(irq=True)
        assert core.model.irq_pc==0
        await core.step();await core.step();assert core.model.pc==0
        for op in ("bnk 1,worker","st r1,(r0)","bl r7,target","bra target"):
            p=assemble(f"{op}\ntarget:bra target\n.bank 1\nworker:bkr")
            core=Core(dut,c.trace,p);await core.reset()
            for _ in range(7):await core.step(enable=False,irq=True)
            assert not core.writes and core.model.sp==0
            await core.step()


@cocotb.test(timeout_time=1,timeout_unit="ms")
async def cpu_reset_with_stack_and_irq_context(dut):
    with Case(dut,"cpu_reset_with_stack_and_irq_context") as c:
        p=assemble(IRQ_PREFIX+"bnk 2,subject\ndestination:bra destination\n.bank 2\nsubject:add r3,r1,r2\nbkr")
        core=Core(dut,c.trace,p);await core.reset();await core.run_to("subject");await core.step(irq=True)
        assert core.model.sp==1 and core.model.irq_bank==2
        await core.reset()
        assert core.model.sp==0 and core.model.irq_bank==0 and core.model.regs==[0]*8
