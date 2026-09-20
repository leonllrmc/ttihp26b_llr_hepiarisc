"""Deterministic stepping, per-test traces, bounded waits and assertions."""
import base64
import json
import os
import random
from collections import Counter, deque
from pathlib import Path

from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

SEED = int(os.getenv("HEPIA_SEED", "260219"), 0)
# cocotb 2.0.1 reads its filter after discovering/importing the test modules.
# Transport regexes outside make's unquoted command assignments: anchors,
# alternation, spaces, and shell metacharacters remain literal data.
if "HEPIA_FILTER_B64" in os.environ:
    os.environ["COCOTB_TEST_FILTER"] = base64.b64decode(os.environ["HEPIA_FILTER_B64"]).decode()


def value(handle):
    try:
        return int(handle.value)
    except ValueError as e:
        raise AssertionError(f"Unknown/X/Z value on {handle._path}: {handle.value}") from e


class Trace:
    def __init__(self, dut, name):
        self.dut, self.name = dut, name
        self.level = os.getenv("HEPIA_TRACE", "quiet")
        self.protocol = os.getenv("HEPIA_PROTOCOL", "0") == "1"
        self.ring = deque(maxlen=80)
        self.counts = Counter()
        self.directory = Path(os.getenv("HEPIA_OUTPUT", "results"))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / (name + ".jsonl")
        self.file = self.path.open("w")
        self.event("metadata", seed=SEED, test=name, shift_v=os.getenv("HEPIA_SHIFT_V", "legacy"), systick=os.getenv("HEPIA_SYSTICK", "rtl"))

    def event(self, kind, **payload):
        event = dict(time_ns=float(get_sim_time(unit="ns")), kind=kind, **payload)
        self.counts[kind] += 1
        self.ring.append(event)
        enabled = kind in ("metadata", "summary", "failure") or self.level == "cycles" or (
            self.level == "instructions" and kind in ("instruction", "alu", "timer", "check")) or (
            self.protocol and kind.startswith(("spi", "i2c")))
        if enabled:
            self.file.write(json.dumps(event) + "\n")

    def finish(self, error=None):
        if error:
            self.file.write(json.dumps(dict(kind="failure_context", events=list(self.ring))) + "\n")
            self.dut._log.error("%s; trace: %s", error, self.path)
        self.event("summary", passed=error is None, error=str(error) if error else None, counts=dict(self.counts))
        self.file.close()


class Case:
    def __init__(self, dut, name):
        self.trace = Trace(dut, name)
        self.rng = random.Random(SEED)
    def __enter__(self): return self
    def __exit__(self, typ, error, tb): self.trace.finish(error)


class Clocked:
    def __init__(self, dut, trace):
        self.dut, self.trace, self.cycles = dut, trace, 0
        self.peers = []

    async def tick(self, count=1):
        for _ in range(count):
            self.dut.clk.value = 0
            await Timer(10, unit="ns")
            self.dut.clk.value = 1
            await Timer(1, unit="ns")
            self.cycles += 1
            for peer in self.peers:
                peer.sample()
            if self.trace.level == "cycles": self.trace.event("cycle", cycle=self.cycles)
            await Timer(9, unit="ns")

    async def reset(self, cycles=3):
        self.dut.rst_n.value = 0
        await self.tick(cycles)
        self.dut.rst_n.value = 1
        await self.tick()

    async def until(self, predicate, limit, description):
        for _ in range(limit):
            if predicate(): return
            await self.tick()
        raise AssertionError(f"Timeout after {limit} clocks waiting for {description}")


class Errors:
    def __init__(self, trace): self.trace, self.counts, self.examples = trace, Counter(), []
    def check(self, field, actual, expected, **context):
        if actual != expected:
            self.counts[field] += 1
            if len(self.examples) < 12:
                item = dict(field=field, actual=actual, expected=expected, **context)
                self.examples.append(item)
                self.trace.event("failure", **item)
    def finish(self):
        assert not self.counts, f"Mismatches {dict(self.counts)}; first examples: {self.examples}"
