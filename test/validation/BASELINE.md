# HEPIARISC validation baseline — 19 September 2026

## Result and scope

**The current RTL does not satisfy the agreed architectural contract.** The
regression contains **81 cocotb tests: 61 pass, 20 fail, none skipped** in the full
default run. Those 20 failures share several causes; they are not 20 independent
defects. All six Verilator builds complete successfully. Failing tests retain
ordinary assertions and make the runner return a nonzero exit status.

The reviewed RTL is commit
[`f8dfddddb4f8c532aaa0dafb3bfc8fd0f59e98a6`](https://github.com/leonllrmc/ttihp26b_llr_hepiarisc/commit/f8dfddddb4f8c532aaa0dafb3bfc8fd0f59e98a6).
The suite is an addition under `test/validation/`; no design RTL was modified.
The register-bank, interrupt and systick contracts are recorded in
[README.md](README.md#architectural-contract-used-by-the-tests).

| Suite | Pass | Fail | Interpretation |
|---|---:|---:|---|
| ALU | 10 | 1 | SUB C/V are incorrect for the comparison contract. Shift V is separately characterized. |
| CPU | 24 | 17 | SUB-dependent comparisons and IRQ/control-flow collisions fail. |
| Systick | 2 | 0 | Matches the accepted current instruction-based timing. |
| User SPI block | 4 | 0 | Byte data, timing, busy, pipeline and reset cases pass. |
| User I²C block | 6 | 0 | Data, ACK/NAK, timing, stretching and reset cases pass. |
| Full chip | 15 | 2 | One IRQ arrival phase hangs; a pending IRQ survives reset. |
| **Total** | **61** | **20** | **Functional approval withheld pending fixes and regression.** |

Local tools: Verilator 5.052, cocotb 2.0.1, Python 3.13. The runner reports Python
3.13.12 and the simulator's embedding reports 3.13.9. Seed: `260219`. Default
profiles: `--shift-v legacy --systick rtl`, standalone SPI divider 4, standalone
I²C divider 4, production full-chip I²C divider 125 at 50 MHz.

The exhaustive ALU tests actually finish all **524,288 operand combinations**,
plus 768 separate shift-V samples. Some failing CPU tests stop on their first
discrepancy; subsequent trials in those tests have **not** been validated. In
particular, the random mixed-program test stops at SUB. Scenario inventory is
not a claim of completed coverage past a failed assertion.

## Confirmed findings

### F01 — High: SUB flags break signed and unsigned comparisons

**Observed:** arithmetic result, N and Z pass for all 65,536 SUB operand pairs.
C disagrees with the no-borrow contract on **65,536/65,536** pairs. V disagrees
with signed subtraction overflow on **32,768/65,536** pairs.

Examples:

* `0 - 0`: expected C=1; observed C=0. Consequently `BGEU` is false and `BLTU`
  true for equal operands.
* `0 - 1`: result `0xff` represents −1 without signed overflow; expected V=0,
  observed V=1. Consequently signed less-than/greater-than conditions are wrong.

**Cause:** [`hepiarisc_alu.sv`](../../src/hepiarisc_alu.sv), lines 35–46, uses the
extended subtraction's borrow bit directly as C and an addition-style sign
comparison for subtraction V. The branch decoder uses the no-borrow convention
and N/V signed comparisons in [`hepiarisc.sv`](../../src/hepiarisc.sv), lines
169–185.

**Correction target:** make the flag convention and condition mnemonics agree;
under this suite's contract C is `A >= B`, and subtraction V requires opposite
operand signs and a result sign different from A. Re-run exhaustive SUB and
the independent numeric branch tests. ADD, including signed overflow, passes
all 65,536 combinations at this revision.

```sh
python run.py --suite alu --test 'alu_sub_exhaustive$' --output results-sub
python run.py --suite cpu --test 'cpu_compare_' --trace instructions --output results-compare
```

### F02 — High: control-flow instructions defeat interrupt entry

**Observed:** an IRQ accepted with BRA, BL, BR or a taken conditional branch
leaves PC at the branch destination instead of IRQ vector 1. For example,
`BRA destination` at bank 0/address `0x14` with destination `0x60` produces
PC=`0x60`, expected PC=`0x01`. BL does write its link register, so the issue is
the inconsistent final control transfer.

**Cause:** [`hepiarisc.sv`](../../src/hepiarisc.sv), lines 275–287, gives those
instructions priority over `irq_sig` for PC. The bank logic gives IRQ priority,
so interrupt entry and instruction completion are not applied consistently.

**Correction target:** first compute the completed instruction's architectural
continuation and side effects, then redirect bank/PC to the IRQ vector while
saving that continuation.

```sh
python run.py --suite cpu --test 'cpu_irq_(branch|call|return|condition_taken)$' --trace instructions
```

### F03 — High: BR saves the wrong continuation when interrupted

**Observed:** `BR r7` at PC=`0x14`, r7=`0x60`, with IRQ saves return PC=`0x15`;
the agreed continuation is `0x60`. This mismatch is reported alongside F02,
so fixing vector priority alone would still leave a wrong return address.

**Cause:** the `next_PC` expression in
[`hepiarisc.sv`](../../src/hepiarisc.sv), lines 299–315, has no BR case and falls
back to PC+1.

**Correction target:** use the register target as BR's continuation PC.
Reproduce with `--suite cpu --test 'cpu_irq_return$' --trace instructions`.

### F04 — High: IRQ suppresses BNK/BKR stack effects

**Observed:** when IRQ coincides with BNK, vector entry occurs but the caller
frame is not pushed: SP stays 0 instead of becoming 1, and the return slot stays
zero instead of `(bank 0, PC 0x15)`. When IRQ coincides with BKR, SP stays 1
instead of becoming 0. Saved continuation alone cannot repair the damaged call
stack when the interrupted program resumes.

**Cause:** the stack updates sit in `else if` branches after the IRQ case in
[`hepiarisc.sv`](../../src/hepiarisc.sv), lines 252–265.

**Correction target:** complete the push/pop on the retirement boundary even
when the final bank/PC transfer is to the IRQ vector. Ordinary bank calls and
returns, all 16 banks, same-bank calls and eight nested frames pass without IRQ.

```sh
python run.py --suite cpu --test 'cpu_irq_bank_(call|return)$' --trace instructions
```

### F05 — High: new IRQ on BIR saves ISR bank/flags instead of restored context

**Observed:** the test interrupts bank 2, then arranges distinct ISR flags before
injecting another IRQ on BIR. Expected new saved context is bank 2, PC=`0x41`,
NZCV=`1000`; observed saved context is bank 0, PC=`0x41`, NZCV=`0000`. The active
PC is also `0x41` instead of IRQ vector 1. The test therefore checks bank and
flag preservation independently of the PC-priority defect.

**Cause:** `nextBank` does not include BIR restoration, `next_alu_flag_*` does
not include BIR-restored flags, and BIR has PC priority over IRQ. See
[`hepiarisc.sv`](../../src/hepiarisc.sv), lines 125–128, 213–234 and 284–287.

**Correction target:** use the post-BIR restored state as the continuation saved
for the new IRQ. This is successive acceptance at a retirement boundary; the
test does not assume an additional hardware nesting stack.

```sh
python run.py --suite cpu --test 'cpu_irq_on_bir$' --trace instructions
```

### F06 — High: one IRQ arrival phase leaves the program trapped in its handler

**Observed:** the full-chip phase sweep injects a single external pulse at 13
fetch/execution offsets. Injection in state 5 (`STATE_SPI_DATA1`) after 17 extra
clocks fails to reach `done` within 20,000 clocks. The other 12 offsets complete
with exactly one ISR execution and all 25 main-program increments.

**Cause indicated by RTL and execution trace:**
[`project.sv`](../../src/project.sv), lines 373–390, arms clearing only when the
raw request is low during `STATE_CPU_EXEC`. A request at that phase can remain
pending after its first CPU acceptance. The next ISR instruction accepts it
again and overwrites the one-level saved context, producing a return into the
handler.

The instruction trace shows the repeated acceptance directly:

| Retired instruction | PC before → after | Pending IRQ before → after |
|---|---|---|
| Main `add r3,r3,r2` | `0x16 → 0x01` | `1 → 1` |
| ISR `ldconst r4,1` | `0x01 → 0x01` | `1 → 0` |
| ISR `ldconst r4,1` again | `0x01 → 0x02` | `0 → 0` |
| ISR `bir` after its body | `0x04 → 0x02` | `0 → 0` |

The subsequent handler body and BIR repeat at PCs 2–4 instead of returning to
main-program PC `0x17`.

**Correction target:** tie pending-request consumption to actual CPU acceptance,
with explicit behavior for a simultaneous new request. Validate every phase
again, including the simultaneous external/timer case. Merely changing CPU PC
priority does not repair this top-level handshake.

```sh
python run.py --suite soc --test 'soc_irq_fetch_phase_sweep$' --trace cycles --protocol --output results-phase
```

### F07 — High: a pending interrupt survives reset

**Observed:** after an external request is latched, asserting reset for five
clocks leaves `irq_pending=1`; expected 0. This is a warm-reset reproduction,
so it does not depend on the simulator's power-on value for an uninitialized
register.

**Cause:** `hepiarisc_irq_latched` has no assignment in the reset branch of
[`project.sv`](../../src/project.sv), lines 265–295.

**Correction target:** clear the pending latch on reset and verify that no
pre-reset event is delivered after reboot.

```sh
python run.py --suite soc --test 'soc_reset_clears_pending_irq$' --trace cycles --output results-reset
```

## Mapping of all failing tests

| Tests | Count | Findings |
|---|---:|---|
| `alu_sub_exhaustive` | 1 | F01 |
| `cpu_register_decode_sub`, `cpu_seeded_mixed_programs` | 2 | F01; later trials stop at the first mismatch |
| `cpu_compare_bgeu`, `bltu`, `bgtu`, `bleu` (same prefix) | 4 | F01 carry |
| `cpu_compare_bge`, `blt`, `bgt`, `ble` (same prefix) | 4 | F01 overflow |
| `cpu_irq_branch`, `cpu_irq_call`, `cpu_irq_condition_taken` | 3 | F02 |
| `cpu_irq_return` | 1 | F02 + F03 |
| `cpu_irq_bank_call`, `cpu_irq_bank_return` | 2 | F04 |
| `cpu_irq_on_bir` | 1 | F05, including PC-priority behavior |
| `soc_irq_fetch_phase_sweep` | 1 | F06 |
| `soc_reset_clears_pending_irq` | 1 | F07 |
| **Total** | **20** | |

## Checks that pass and contract characterizations

The passing full-chip scenarios include all 16 flash banks, all 80 RAM bytes,
signed address wrapping, all 16 GPIO direction masks × 16 output patterns,
every GPO/GPI pattern, all 256 user SPI byte exchanges, production-speed I²C
read/write/NAK/repeated START/STOP/stretching, and overlapping I²C/SPI/GPIO with
and without IRQ. IRQ during a non-control instruction restores the continuation;
banked IRQ flash fetching also passes. Reset during flash, SPI and I²C transfers
passes the tested recovery checks. These results do not cancel F01–F07.

Systick matches **`8*divider+1` enabled instruction slots**, as requested for
this baseline. Divider 0 fires on every enabled slot. It is not a wall-clock
timer, and flash/SPI stalls do not advance it. MMIO reload and source selection
are checked. This timing is documented behavior, not counted as a defect.

Shift V uses a separate compatibility profile: LSL/LSR V=0; ASR V is true when
input bits 7 and 6 match. Passing those characterization tests does not approve
that convention as signed overflow. `--shift-v arithmetic` and `--systick exact`
are explicit alternate-contract experiments, excluded from baseline approval.

Stack overflow overwrites older circular-stack entries, and underflow wraps the
pointer. Those are separately labelled characterization scenarios outside the
valid eight-frame contract; they are not reported as valid-program failures.

Additional runs: standalone SPI at divider 1 passes **4/4**. The Icarus 13.0
systick and I²C suites pass **8/8**; CPU and SPI elaboration fail on pre-existing
forward declarations, so the complete suite is supported on Verilator here.
The assembler's four host tests pass, and the example firmware assembles to an
8192-byte image. The GitHub workflow is supplied but has not run remotely.

## Reproduction and evidence

Run from `test/validation/` after the installation steps in [README.md](README.md):

```sh
python -m unittest -v test_assembler_host
python run.py --suite all --protocol --output results
python trace_view.py results/cpu/cpu_irq_return.jsonl
python trace_view.py results/soc/soc_i2c_mmio_normal.jsonl --kind i2c
```

The full regression is expected to exit **1** on this RTL. Each suite has
`results.xml` and `sim.log`; `summary.json` records the exact source hashes,
tool versions, configuration and test outcomes. Every test also writes JSONL;
quiet failures retain a context buffer. Use `--trace instructions` for the full
execution or `--trace cycles --protocol` for internal state and bus events.
Filtered runs list unselected tests as skipped in cocotb XML; they are not
silently counted as passes. A selection that executes no tests fails the runner.

The delivery archive contains code, this report, the usage guide, and baseline
evidence. The patch contains only repository additions and the test-guide link.

## Approval boundary

This is a functional RTL validation report. It does not replace DRC/LVS, static
timing/SDF, CDC/reset-domain review, analog pad and pull-up checks, or foundry
signoff. Verilator is primarily two-state; the passing tests are not a proof of
power-up X safety. GPIO and protocol peers are synchronously driven. No formal
proof or exhaustive CPU-state/interleaving coverage is claimed.

The next acceptance step is to correct F01–F07, re-run the same suite without
weakening its assertions, and investigate any later checks exposed once the
current first failures are removed.
