#!/usr/bin/env python3
"""Run independent regressions and preserve every suite result, even on failure."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import platform
from importlib.metadata import version
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", nargs="+", choices=["all", "alu", "cpu", "systick", "spi", "i2c", "soc"], default=["all"])
    parser.add_argument("--sim", choices=["verilator", "icarus"], default="verilator")
    parser.add_argument("--test", default="", help="cocotb test-name regular expression")
    parser.add_argument("--trace", choices=["quiet", "instructions", "cycles"], default="quiet")
    parser.add_argument("--protocol", action="store_true", help="Log decoded SPI/I2C events in JSONL")
    parser.add_argument("--seed", default="260219")
    parser.add_argument("--stress", action="store_true", help="Increase deterministic random cases")
    parser.add_argument("--shift-v", choices=["legacy", "arithmetic"], default="legacy")
    parser.add_argument("--systick", choices=["rtl", "exact"], default="rtl")
    parser.add_argument("--spi-div", type=int, default=4, help="Standalone SPI half-period; full chip uses 1")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent/"results")
    args = parser.parse_args()
    try: re.compile(args.test)
    except re.error as e: parser.error(f"invalid test regex: {e}")
    if args.spi_div < 1: parser.error("SPI divider must be positive")
    here = Path(__file__).resolve().parent
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    suites = ["alu", "cpu", "systick", "spi", "i2c", "soc"] if "all" in args.suite else args.suite
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, text=True, capture_output=True).stdout.strip()
    source_hashes={str(p.relative_to(here.parent.parent)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for folder,pattern in ((here,"*.py"),(here,"*.sv"),(here.parent.parent/"src","*"))
                   for p in sorted(folder.glob(pattern)) if p.is_file()}
    sim_version=subprocess.run(["verilator","--version"] if args.sim=="verilator" else ["iverilog","-V"],capture_output=True,text=True).stdout.splitlines()[0]
    summary = dict(commit=revision,started_utc=datetime.now(timezone.utc).isoformat(),
                   tools=dict(python=platform.python_version(),cocotb=version("cocotb"),simulator=sim_version),source_sha256=source_hashes,
                   configuration={k: str(v) if isinstance(v, Path) else v for k,v in vars(args).items()}, suites={})
    failed = False
    for suite in suites:
        directory = output / suite
        directory.mkdir(exist_ok=True)
        xml = directory / "results.xml"
        xml.unlink(missing_ok=True)
        env = os.environ | {"HEPIA_TRACE":args.trace, "HEPIA_PROTOCOL":str(int(args.protocol)),
             "HEPIA_SEED":args.seed, "HEPIA_STRESS":str(int(args.stress)), "HEPIA_SHIFT_V":args.shift_v,
             "HEPIA_SYSTICK":args.systick, "HEPIA_SPI_DIV":str(args.spi_div),
             "HEPIA_OUTPUT":str(directory), "COCOTB_TEST_FILTER":"", "COCOTB_TESTCASE":"",
             "HEPIA_FILTER_B64":base64.b64encode(args.test.encode()).decode()}
        command = ["make", "-f", str(here/"Makefile"), f"SUITE={suite}", f"SIM={args.sim}",
                   f"SPI_DIV={args.spi_div}",
                   f"SIM_BUILD={here/'build'/f'{args.sim}-{suite}-spi{args.spi_div}'}",
                   f"COCOTB_RESULTS_FILE={xml}"]
        print(f"Running {suite} ({args.sim}); log: {directory/'sim.log'}", flush=True)
        with (directory/"sim.log").open("w") as log:
            process = subprocess.run(command, cwd=here, env=env, stdout=log, stderr=subprocess.STDOUT)
        cases = []
        if xml.exists():
            for node in ET.parse(xml).iter("testcase"):
                status = "fail" if node.find("failure") is not None or node.find("error") is not None else "skip" if node.find("skipped") is not None else "pass"
                cases.append(dict(name=node.get("name"),status=status))
        passed = sum(c["status"] == "pass" for c in cases)
        fail = sum(c["status"] == "fail" for c in cases)
        skipped = sum(c["status"] == "skip" for c in cases)
        infrastructure_error = not (passed or fail) or (process.returncode != 0 and fail == 0)
        failed |= bool(fail or infrastructure_error)
        summary["suites"][suite] = dict(returncode=process.returncode,passed=passed,failed=fail,skipped=skipped,infrastructure_error=infrastructure_error,cases=cases)
        (output/"summary.json").write_text(json.dumps(summary, indent=2))
        print(f"  {passed} pass, {fail} fail, {skipped} skip; infrastructure_error={infrastructure_error}",flush=True)
    return int(failed)


if __name__ == "__main__": sys.exit(main())
