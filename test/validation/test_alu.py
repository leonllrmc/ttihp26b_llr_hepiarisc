import cocotb
from cocotb.triggers import Timer
from assembler import ALU
from common import Case, Errors, value
from reference import alu


def make_test(op):
    async def test(dut):
        with Case(dut,"alu_"+op) as case:
            errors=Errors(case.trace);dut.op.value=ALU[op]
            for a in range(256):
                for b in range(256):
                    dut.a.value=a;dut.b.value=b
                    await Timer(1,unit="ns")
                    result,flags=alu(op,a,b)
                    observed=(value(dut.n),value(dut.z),value(dut.c),value(dut.v))
                    errors.check("result",value(dut.result),result,a=a,b=b)
                    for name,actual,expected in zip("NZCV",observed,flags):
                        if op in ("lsl","lsr","asr") and name=="V":continue  # Separate contract checks below.
                        errors.check(name,actual,expected,a=a,b=b)
                    case.trace.event("alu",op=op,a=a,b=b,result=value(dut.result),flags=observed,expected_result=result,expected_flags=flags)
            case.trace.event("check",vectors=65536,mismatches=dict(errors.counts))
            errors.finish()
    test.__name__="alu_"+op+"_exhaustive"
    test.__qualname__=test.__name__
    return cocotb.test(timeout_time=1,timeout_unit="ms")(test)


for operation in ALU: globals()["alu_"+operation+"_exhaustive"]=make_test(operation)


def make_shift_contract(op):
    async def test(dut):
        with Case(dut,"alu_"+op+"_v_contract_characterization") as c:
            errors=Errors(c.trace);dut.op.value=ALU[op];dut.b.value=0
            for a in range(256):
                dut.a.value=a;await Timer(1,unit="ns")
                expected=alu(op,a,0)[1][3]
                c.trace.event("alu",op=op,a=a,V=value(dut.v),expected_V=expected,classification="shift overflow profile, not an approved arithmetic definition")
                errors.check("V",value(dut.v),expected,a=a)
            errors.finish()
    test.__name__="alu_"+op+"_v_contract_characterization";test.__qualname__=test.__name__
    return cocotb.test(timeout_time=1,timeout_unit="ms")(test)


for shift in ("lsl","lsr","asr"):globals()["alu_"+shift+"_v_contract_characterization"]=make_shift_contract(shift)
