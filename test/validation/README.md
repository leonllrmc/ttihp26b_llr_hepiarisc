# HEPIARISC architectural and peripheral validation

This is an independent cocotb regression for `tt_um_llr_hepiarisc`. It tests the
ALU, CPU, systick, SPI and I²C blocks separately, then executes assembled programs
through the complete flash/MMIO/GPIO interface. Design defects produce ordinary
test failures and a nonzero exit status; they are not hidden with expected-failure
markers. The original `test/test.py` remains available as a separate smoke test.

The baseline was exercised against RTL commit
`f8dfddddb4f8c532aaa0dafb3bfc8fd0f59e98a6`. See [BASELINE.md](BASELINE.md) for results
and the mapping from failures to design issues.

## Quick start

Requirements: Python 3.11–3.13, `make`, a C++ compiler, and **Verilator 5.036 or
newer**. Install the repository's pinned Python dependencies. The tested local
combination is Python 3.13, cocotb 2.0.1 and Verilator 5.052 (the local runner
reports Python 3.13.12; the simulator embedding reports 3.13.9).
[cocotb's simulator requirements](https://docs.cocotb.org/en/v2.0.1/simulator_support.html#verilator)
explain the minimum version.

From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r test/requirements.txt
cd test/validation
python -m unittest -v test_assembler_host
python run.py --suite all --protocol
```

The default output directory is `test/validation/results/`. Each suite receives
its own simulator log, JUnit XML, and per-test JSONL files. `summary.json` includes
the commit, configuration, seed, tool versions, source hashes and every selected
test result. The runner continues through independent suites after a failure,
and returns nonzero for any test failure, build error, or empty selection.

Run an individual case, enable its instruction trace and protocol events:

```sh
python run.py --suite cpu --test '^test_cpu.cpu_irq_bank_call$' --trace instructions --output results-irq
python run.py --suite soc --test 'soc_i2c_mmio_normal$' --trace instructions --protocol --output results-i2c
python trace_view.py results-i2c/soc/soc_i2c_mmio_normal.jsonl
python trace_view.py results-i2c/soc/soc_i2c_mmio_normal.jsonl --kind i2c
```

Additional useful runs:

```sh
python run.py --suite spi --spi-div 1 --protocol --output results-spi1
python run.py --suite cpu --test 'cpu_seeded_mixed_programs$' --seed 0x1234 --stress --trace instructions
python run.py --suite soc --test 'soc_irq_fetch_phase_sweep$' --trace cycles --protocol --output results-phase
```

`--trace` is available for every test: `quiet`, `instructions`, or `cycles`.
Instruction traces show assembly, bank/PC, register changes, NZCV, stack state,
IRQ and memory activity. Standalone ALU traces include operands and expected
results/flags. `--protocol` adds decoded flash addresses and bytes, user SPI
TX/RX bytes, I²C START/repeated START/STOP, byte directions, ACK/NAK, bit samples,
clock periods and clock-stretch events. Quiet mode still saves the last 80 events
on failure. An exhaustive ALU run with full tracing creates a large log; a
filtered test is usually easier to inspect.

The filter is a Python regular expression over the full cocotb test name. The
runner transports it without exposing regex metacharacters to the make shell.
Use `run.py --test` for complex filters instead of a raw make variable.

## Coverage map

| Suite | Checks |
|---|---|
| `alu` | All 256×256 operand pairs for every operation: 524,288 combinations. Result and N/Z/C; arithmetic V for ADD/SUB. Shift V has three separately named contract-characterization tests. |
| `cpu` | Every immediate in every register; ALU source/destination decoding and aliasing; all conditions and both outcomes; numeric signed/unsigned comparisons; signed memory displacements; address/PC wrap; BL/BR; non-ALU flag preservation; enable gating and reset. |
| `cpu` banks | All 16 destination banks including same-bank calls, eight nested calls, repeated stack reuse, BL/BR inside banks, and explicitly labelled overflow/underflow characterization. |
| `cpu` IRQ | ALU/immediate/load/store/branch/call/return/taken and untaken condition/BNK/BKR collisions; banked execution; IRQ during BIR; PC wrap; saved flags and context; reset with a live stack/IRQ context. |
| `systick` | Divider 0, 1, 2, 7, 31, 127 and 255; sparse enable; disabled pauses; divider changes; reset; single-cycle pulse semantics. |
| `spi` | Every TX byte with independently varied RX, bit order, clock period, completion timing, busy/done/CS, ignored sends while busy, tail-window pipelining and reset at every transfer phase. Run at divider 4 and 1. |
| `i2c` | Every TX and RX byte; ACK and NAK; repeated START; master ACK then NAK; open-drain feedback; normal bit period/high width; clock stretching including START/STOP; ignored busy commands; ACK preset priority; resets through phases. |
| `soc` | Pin-level flash boot/address/endianness across all banks; all 80 RAM locations and boundaries; all 16 GPIO direction masks × 16 output patterns, all GPO/GPI patterns; 256 user SPI exchanges; I²C MMIO TX/RX/status with production speed and stretching. |
| `soc` concurrency | IRQ timing across fetch phases; source masks and held input; IRQ during user SPI and I²C; concurrent I²C/user SPI/GPIO with and without IRQ; simultaneous timer/external sources; banked IRQ fetch restoration; timer MMIO reload; resets during transfers and with a pending IRQ. |

Every wait has a cycle budget, and every cocotb test has an outer timeout. Fixed
seeds make random cases repeatable. `--stress` increases mixed-program trials.
The RGB register is excluded as requested.

## Architectural contract used by the tests

These choices were confirmed for this validation request. The incomplete ISA
document is not used as the sole oracle.

* Instructions are 16-bit, flash bytes big-endian; PC is an eight-bit **word**
  address, with 16 banks. Flash byte address is `bank*512 + PC*2`.
* `BNK bank,target` pushes **caller bank and PC+1** on an eight-entry hardware
  stack. `BKR` restores that pair. Ordinary `BL`/`BR` use a register and do not
  consume this stack. Arithmetic wraps at the implemented widths.
* An accepted IRQ completes the current instruction, including its register,
  memory and stack effects, then enters **bank 0, PC 1**. It saves the continuation
  bank/PC and post-instruction flags. `BIR` restores that context. IRQ priority
  must apply consistently to PC, bank, flags and stack effects.
* The IRQ context is one level deep. This suite does not assume an undocumented
  hardware nesting stack. The timer integration handler masks/re-enables its
  source to avoid nesting. The IRQ-on-BIR test checks a new interrupt at the
  retirement boundary after the previous context has been restored.
* External IRQ is rising-edge detected despite the pin's `irq_n` label. The
  top-level retains a pending request until actual CPU acceptance. Simultaneous
  timer/external pulses coalesce into one request; this is not an event counter.
* LD/ST displacements are **signed −32…+31**, and effective addresses wrap modulo
  256. Full-chip RAM is **80 bytes**, `0x00…0x4f`.
* SUB's carry is expected to mean **no borrow**, consistent with the defined
  BGEU/BLTU/BGTU/BLEU conditions. Numeric comparison tests also check the final
  branch decision independently of the ALU flag tests.
* Condition-decoder tests deliberately feed it the ALU flags actually observed,
  then check the decoder's boolean function. They do **not** certify that those
  flags are arithmetically correct; the exhaustive ALU and numeric comparisons
  are independent checks of that.

### Systick timing and ambiguous shift overflow

The accepted default documents the existing timer: a pulse every
**`8*divider + 1` enabled instruction slots**, including divider zero → one slot.
Fetch and peripheral stalls do not advance it. MMIO writes to `0x88` or `0x89`
reload/reset it. A pulse can span consecutive clocks when divider zero and
enable remain continuously asserted; each asserted clock is an enabled event.
`--systick exact` is an **alternative contract experiment**, not the default
acceptance criterion; it requests `max(1,8*divider)`.

The core profile preserves the current shift-V convention so that unrelated
tests can proceed: LSL/LSR V=0, ASR V=1 when input bits 7 and 6 are equal.
Tests named `alu_{lsl,lsr,asr}_v_contract_characterization` check this separately.
Their success does not approve this as a signed-overflow definition. The
optional `--shift-v arithmetic` experiment expects signed overflow for LSL and
V=0 for right shifts. ADD/SUB V always use independent signed arithmetic.

### MMIO and peripheral assumptions

| Address | Function tested |
|---|---|
| `0x80 / 0x81` | GPO output/readback / GPI input |
| `0x82 / 0x83 / 0x84` | GPIO output / direction / resolved pad input |
| `0x88 / 0x89` | IRQ source select / systick divider |
| `0x90 / 0x91` | I²C START / TX byte commands |
| `0x92 / 0x93 / 0x94` | I²C ACK/NAK preset / RX command / STOP |
| `0x95 / 0x96 / 0x97` | I²C busy / received byte / slave ACK bit (0=ACK) |
| `0x98 / 0x99` | User SPI TX exchange / last RX byte |

The flash and user SPI intentionally share MOSI, MISO and the underlying clock.
The flash may see clock edges during a user exchange, **with flash CS high**.
The peer checks this actual selection contract rather than demanding an idle
flash clock. There is no dedicated user CS output in this RTL.

The HDL wrapper resolves I²C lines as wired-AND with pull-ups, independently of
the CPU model, and checks that the master never drives high. Full-chip I²C uses
the **production divider 125** (100 kHz for the 50 MHz clock). `sim_config.sv`
removes the test-only `COCOTB_SIM` speed switch before compiling the unchanged
RTL, and the harness asserts the effective divider. Standalone I²C tests use
divider 4 for faster exhaustive data coverage. Normal bit period and high time
are checked at both speeds; stretching is tested separately.

## Assembler and firmware

Programs in the tests are assembly source, never handwritten opcode arrays.
`assembler.py` is a provided, dependency-free two-pass alternative to customasm.
It emits an 8192-byte flash image, a bank/address/source listing and a symbol map.
The assembler host tests check published encoding anchors, byte ordering, label
relocations, bank placement and rejection of invalid operands/overlaps.

```sh
python assembler.py examples/peripheral_smoke.s -o smoke.bin
```

Supported forms:

```asm
.equ DATA, 0x5a
.bank 0
bra main
.org 1
bir
.org 16
main: ldconst r1, DATA
bnk 3, worker
done: bra done
.bank 3
.org 32
worker: st r1, (r0-1)
bkr
```

`ADD/SUB/AND/OR`, `LSL/LSR/ASR/NOT`, `LDCONST`/`MOVI`, `LD/ST`, `BRA`, every
condition mnemonic, `BRCOND code,target`, `BL rN,target`, `BR rN`, `BIR`, `BNK`,
`BKR`, `TR` and `NOP` are supported. `NOP` is the existing `AND r0,r0,r0` pseudo-op
and therefore updates flags. Expressions support integer literals, constants,
labels, `+`, `-` and `$` for current PC. Labels are ordinary identifiers; local
dotted labels and arbitrary customasm macros are not implemented. `.bank` resets
the origin to zero; use `.org` when reopening a bank. Cross-bank BRA/BL and wrong
bank label operands are rejected. Relative branches use modulo-256 PC arithmetic.

The reference CPU interprets parsed source operations rather than decoding the
assembler's machine words. This avoids sharing the DUT decoder's implementation
with the oracle. CPU unit tests observe PC, registers, flags and stack through
test-only wires; they never force architectural state to make a case pass.

## CI and validation limits

`.github/workflows/validation.yaml` runs each suite independently, also runs SPI
with divider 1, and uploads logs/XML/traces even on failure. It uses a dated OSS
CAD Suite because the stock Ubuntu Verilator is too old for cocotb 2.0.1. This
workflow has been authored locally; hosted execution is not claimed.

`--sim icarus` is available for secondary checks. Local Icarus 13.0 rejects
pre-existing forward declarations in the CPU and SPI RTL. Such elaboration
errors are reported as infrastructure failures, not as passing or skipped tests.
Use Verilator for the complete suite; no RTL compatibility edits are applied.

These are RTL functional/protocol tests. They do not establish CDC/metastability,
analog pull-up/rise-time margins, real-flash timing, SDF timing or physical
signoff. GPIO inputs and the protocol peers are driven synchronously by the
harness. Stack overflow/underflow and shift overflow are characterized separately
from valid-program acceptance. Coverage here names exercised scenarios; no claim
of formal exhaustive CPU-state or all-interleaving coverage is made.
