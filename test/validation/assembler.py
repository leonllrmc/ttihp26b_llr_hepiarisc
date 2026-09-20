#!/usr/bin/env python3
"""Small two-pass HEPIARISC assembler; no third-party dependency or eval().

All addresses in assembly are instruction words, relative to their bank.
The resulting flash image is bank-major, with big-endian 16-bit words.
BNK/BKR implement the actual opcode layout missing from customasm_sample.s.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

ALU = {name: i for i, name in enumerate("add sub lsl lsr asr and or not".split())}
CONDITIONS = dict(zip("bvc bvs bcs bcc bns bnc bgt bge bzs bzc blt ble bgtu bleu".split(), range(14)))
CONDITIONS.update(bgeu=2, bltu=3, beq=8, bne=9)


class AssemblyError(ValueError):
    pass


@dataclass(frozen=True)
class Instruction:
    mnemonic: str
    args: tuple[int, ...]
    bank: int
    pc: int
    line: int
    source: str
    word: int


@dataclass
class Program:
    instructions: dict[tuple[int, int], Instruction]
    labels: dict[str, tuple[int, int]]

    def at(self, bank: int, pc: int) -> Instruction:
        try:
            return self.instructions[bank, pc]
        except KeyError as e:
            raise AssertionError(f"Execution reached unassembled address {bank:x}:{pc:02x}") from e

    def address(self, label: str) -> tuple[int, int]:
        return self.labels[label.lower()]

    def image(self) -> bytes:
        # Unoccupied flash words execute a self-branch, encoded by the same
        # assembler instruction encoder; at() still rejects holes in CPU tests.
        fill = encode("bra", (0,), 0, 0)
        words = [fill] * (16 * 256)
        for (bank, pc), ins in self.instructions.items():
            words[bank * 256 + pc] = ins.word
        return b"".join(word.to_bytes(2, "big") for word in words)

    def listing(self) -> str:
        return "\n".join(f"{b:x}:{pc:02x} {ins.word:04x}  {ins.source}"
                         for (b, pc), ins in sorted(self.instructions.items())) + "\n"


def bounded(value: int, lo: int, hi: int, what: str) -> int:
    if not lo <= value <= hi:
        raise AssemblyError(f"{what} out of range [{lo}, {hi}]: {value}")
    return value


def expression(text: str, names: dict[str, int], pc: int = 0) -> int:
    text = re.sub(r"\$([0-9a-fA-F]+)", r"0x\1", text.strip()).replace("$", "__pc")
    names = dict(names, __pc=pc)
    def walk(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id.lower() in names:
            return names[node.id.lower()]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return walk(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            return walk(node.left) + walk(node.right) * (-1 if isinstance(node.op, ast.Sub) else 1)
        raise AssemblyError(f"Unsupported or unresolved expression: {text}")
    try:
        return walk(ast.parse(text, mode="eval").body)
    except (SyntaxError, RecursionError) as e:
        raise AssemblyError(f"Invalid expression: {text}") from e


def register(text: str) -> int:
    m = re.fullmatch(r"r([0-7])", text.strip().lower())
    if not m:
        raise AssemblyError(f"Expected r0..r7, got {text!r}")
    return int(m[1])


def encode(op: str, args: tuple[int, ...], bank: int, pc: int) -> int:
    if op in ALU:
        rd, ra, rb = args
        return (ALU[op] << 12) | (rd << 9) | (ra << 6) | (rb << 3)
    if op == "ldconst":
        return 0x8000 | (args[0] << 9) | (args[1] & 255)
    if op in ("bra", "brcond"):
        cond, dest = (0, args[0]) if op == "bra" else args
        # PC is eight bits: wraparound is architectural, not a relocation bug.
        return (0xB000 if op == "bra" else 0xA000 | (cond << 8)) | ((dest - pc) & 255)
    if op in ("ld", "st"):
        rd, rp, off = args
        return (0xC000 if op == "ld" else 0xD000) | (rd << 9) | (rp << 6) | (off & 63)
    if op == "bl":
        return 0xE000 | (args[0] << 9) | args[1]
    if op == "br":
        return 0xF000 | (args[0] << 9)
    if op == "bir":
        return 0xF001
    if op == "bkr":
        return 0xF003
    if op == "bnk":
        return 0x9000 | (args[0] << 8) | args[1]
    raise AssemblyError(f"Unknown instruction: {op}")


def assemble(source: str) -> Program:
    bank = pc = 0
    labels: dict[str, tuple[int, int]] = {}
    constants: dict[str, int] = {}
    pending = []
    for line_no, raw in enumerate(source.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        try:
            while (m := re.match(r"^([A-Za-z_]\w*):\s*", line)):
                name = m[1].lower()
                if name in labels or name in constants:
                    raise AssemblyError(f"Duplicate symbol: {name}")
                bounded(pc, 0, 255, "label PC")
                labels[name] = (bank, pc)
                line = line[m.end():]
            if not line:
                continue
            if line.lower().startswith(".equ "):
                fields = re.split(r"\s*,\s*|\s+", line[5:].strip(), maxsplit=1)
                if len(fields)!=2:raise AssemblyError("Use .equ name, value")
                name, value = fields
                name = name.lower()
                if not re.fullmatch(r"[a-z_]\w*", name) or name in labels or name in constants:
                    raise AssemblyError(f"Invalid/duplicate constant: {name}")
                constants[name] = expression(value, constants, pc)
                continue
            if line.lower().startswith(".bank "):
                bank = bounded(expression(line[6:], constants), 0, 15, "bank")
                pc = 0
                continue
            if line.lower().startswith(".org "):
                pc = bounded(expression(line[5:], constants), 0, 255, "origin")
                continue
            bounded(pc, 0, 255, "PC; use .bank or .org before crossing bank end")
            pending.append((bank, pc, line_no, line))
            pc += 1
        except AssemblyError as e:
            raise AssemblyError(f"line {line_no}: {e}") from e

    instructions = {}
    names = {name: address[1] for name, address in labels.items()} | constants
    for bank, pc, line_no, line in pending:
        try:
            if (bank, pc) in instructions:
                raise AssemblyError(f"Overlapping output at {bank:x}:{pc:02x}")
            parts = line.lower().split(None, 1)
            op, tail = parts[0], parts[1] if len(parts) == 2 else ""
            operands = [s.strip() for s in tail.split(",")] if tail else []
            # Permit the existing customasm BL spelling (bl r7 target).
            if op == "bl" and len(operands) == 1:
                operands = tail.split(None, 1)
            def count(n):
                if len(operands) != n:
                    raise AssemblyError(f"{op} requires {n} operands")
            def addr(s, target_bank=bank):
                for name in re.findall(r"[a-z_]\w*", s.lower()):
                    if name in labels and labels[name][0] != target_bank:
                        raise AssemblyError(f"Cross-bank target {name}; use BNK with its bank")
                return bounded(expression(s, names, pc), 0, 255, "target address")
            if op in ("movi",): op = "ldconst"
            if op == "nop":
                count(0); op, args = "and", (0, 0, 0)
            elif op == "tr":
                count(2); op, args = "and", (register(operands[0]), register(operands[1]), register(operands[1]))
            elif op in ALU:
                count(2 if op in ("lsl", "lsr", "asr", "not") else 3)
                args = tuple(register(x) for x in operands)
                if len(args) == 2: args += (0,)
            elif op == "ldconst":
                count(2); args = (register(operands[0]), bounded(expression(operands[1], names, pc), -128, 255, "byte") & 255)
            elif op in CONDITIONS:
                count(1); args = (CONDITIONS[op], addr(operands[0])); op = "brcond"
            elif op == "brcond":
                count(2); args = (bounded(expression(operands[0], names), 0, 15, "condition"), addr(operands[1]))
            elif op == "bra":
                count(1); args = (addr(operands[0]),)
            elif op in ("ld", "st"):
                count(2)
                m = re.fullmatch(r"\(\s*(r[0-7])\s*([+-].+)?\)", operands[1])
                if not m: raise AssemblyError("Use (rN + signed_offset) for memory operands")
                args = (register(operands[0]), register(m[1]), bounded(expression(m[2] or "0", names, pc), -32, 31, "memory displacement"))
            elif op == "bnk":
                count(2); dest_bank = bounded(expression(operands[0], names), 0, 15, "bank")
                args = (dest_bank, addr(operands[1], dest_bank))
            elif op == "bl":
                count(2); args = (register(operands[0]), addr(operands[1]))
            elif op == "br":
                count(1); args = (register(operands[0]),)
            elif op in ("bir", "bkr"):
                count(0); args = ()
            else:
                raise AssemblyError(f"Unknown instruction or directive: {op}")
            instructions[bank, pc] = Instruction(op, args, bank, pc, line_no, line, encode(op, args, bank, pc))
        except (AssemblyError, IndexError) as e:
            raise AssemblyError(f"line {line_no} ({line}): {e}") from e
    return Program(instructions, labels)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args()
    program = assemble(args.source.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(program.image())
    args.output.with_suffix(".lst").write_text(program.listing())
    args.output.with_suffix(".symbols.json").write_text(json.dumps(program.labels, indent=2))


if __name__ == "__main__":
    main()
