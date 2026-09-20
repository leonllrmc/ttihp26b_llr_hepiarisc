"""Architectural expectations, evaluated from source instructions, not RTL."""
from dataclasses import dataclass, field
import os


def signed8(value):
    return value - 256 if value & 128 else value


def alu(op, a, b):
    carry = overflow = 0
    if op == "add":
        raw = a + b
        carry = int(raw > 255)
        overflow = int(not -128 <= signed8(a) + signed8(b) <= 127)
    elif op == "sub":
        raw = a - b
        carry = int(a >= b)  # Required by BGEU/BGTU/BLTU/BLEU.
        overflow = int(not -128 <= signed8(a) - signed8(b) <= 127)
    elif op == "lsl":
        raw, carry = a * 2, a // 128
        if os.getenv("HEPIA_SHIFT_V", "legacy") == "arithmetic":
            overflow = int(not -128 <= signed8(a)*2 <= 127)
    elif op == "lsr": raw, carry = a // 2, a % 2
    elif op == "asr":
        raw, carry = signed8(a) // 2, a % 2
        # This is explicitly a compatibility profile, not an arithmetic
        # overflow definition. Strict mode tests V=0 for right shifts.
        if os.getenv("HEPIA_SHIFT_V", "legacy") == "legacy":
            overflow = int((a >= 128) == (64 <= a % 128))
    elif op == "and": raw = a & b
    elif op == "or": raw = a | b
    elif op == "not": raw = 255 - a
    else: raise ValueError(op)
    result = raw & 255
    return result, (int(result >= 128), int(result == 0), carry, overflow)


def condition(code, flags):
    n, z, c, v = flags
    return bool((not v, v, c, not c, n, not n, not z and n == v,
                 n == v, z, not z, n != v, z or n != v,
                 c and not z, not c or z, False, False)[code])


@dataclass
class CPU:
    regs: list = field(default_factory=lambda: [0] * 8)
    flags: tuple = (0, 0, 0, 0)  # N,Z,C,V
    pc: int = 0
    bank: int = 0
    sp: int = 0
    stack: list = field(default_factory=lambda: [(0, 0)] * 8)
    irq_pc: int = 0
    irq_bank: int = 0
    irq_flags: tuple = (0, 0, 0, 0)
    memory: list = field(default_factory=lambda: [0] * 256)

    def execute(self, ins, irq=False, read_data=None):
        op, args = ins.mnemonic, ins.args
        next_pc = (self.pc + 1) % 256
        if op in ("add", "sub", "lsl", "lsr", "asr", "and", "or", "not"):
            rd, ra, rb = args
            self.regs[rd], self.flags = alu(op, self.regs[ra], self.regs[rb])
        elif op == "ldconst": self.regs[args[0]] = args[1]
        elif op == "bra": next_pc = args[0]
        elif op == "brcond":
            if condition(args[0], self.flags): next_pc = args[1]
        elif op == "bl": self.regs[args[0]], next_pc = next_pc, args[1]
        elif op == "br": next_pc = self.regs[args[0]]
        elif op in ("ld", "st"):
            reg, ptr, offset = args
            address = (self.regs[ptr] + offset) % 256
            if op == "ld": self.regs[reg] = self.memory[address] if read_data is None else read_data
            else: self.memory[address] = self.regs[reg]
        elif op == "bnk":
            self.stack[self.sp] = (self.bank, next_pc)
            self.sp = (self.sp + 1) % 8
            self.bank, next_pc = args
        elif op == "bkr":
            self.sp = (self.sp - 1) % 8
            self.bank, next_pc = self.stack[self.sp]
        elif op == "bir":
            self.bank, next_pc, self.flags = self.irq_bank, self.irq_pc, self.irq_flags
        else: raise ValueError(op)
        self.pc = next_pc
        if irq:
            self.irq_bank, self.irq_pc, self.irq_flags = self.bank, self.pc, self.flags
            self.bank, self.pc = 0, 1


def timer_period(divider):
    # Current implementation counts enabled instruction slots, not wall clocks.
    base = 8 * divider
    return max(1, base if os.getenv("HEPIA_SYSTICK", "rtl") == "exact" else base + 1)
