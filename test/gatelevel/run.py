#!/usr/bin/env python3
"""Run the same pin-only scenarios on RTL and/or the real IHP gate netlist."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=("rtl","gl","both"),default="both")
    p.add_argument("--netlist",type=Path,default=ROOT/"test/gate_level_netlist.v")
    p.add_argument("--pdk-root",type=Path,default=os.getenv("PDK_ROOT"))
    p.add_argument("--provenance",type=Path,help="Optional tt_submission/commit_id.json; rejects a different RTL revision")
    p.add_argument("--clock-ns",type=float,default=json.loads((ROOT/"src/config.json").read_text())["CLOCK_PERIOD"])
    p.add_argument("--i2c-quarter-cycles",type=int,default=125)
    p.add_argument("--test",default="",help="Full cocotb test-name regular expression")
    p.add_argument("--trace",choices=("quiet","transactions","pins"),default="quiet")
    p.add_argument("--protocol",action="store_true")
    p.add_argument("--output",type=Path,default=HERE/"results")
    args=p.parse_args()
    try:re.compile(args.test)
    except re.error as error:p.error(str(error))
    if args.clock_ns<4 or args.i2c_quarter_cycles<1:p.error("Clock period must be >= 4 ns and I2C divider positive")
    modes=["rtl","gl"] if args.mode=="both" else [args.mode]
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    files=[*sorted((ROOT/"src").glob("*.v")),*sorted((ROOT/"src").glob("*.sv"))]
    files += [*sorted(HERE.glob("*.py")),HERE/"tb_pins.sv",HERE/"Makefile",
              *[ROOT/"test/validation"/name for name in ("assembler.py","common.py","protocols.py","reference.py","sim_config.sv")]]
    provenance=None
    if "gl" in modes:
        if not args.netlist.is_file():p.error("Gate netlist not found: specify --netlist; RTL is never substituted")
        if not args.pdk_root:p.error("Specify --pdk-root or set PDK_ROOT")
        args.netlist=args.netlist.resolve();args.pdk_root=args.pdk_root.resolve()
        models=[args.pdk_root/f"ihp-sg13g2/libs.ref/{cell}/verilog/{cell}.v" for cell in ("sg13g2_stdcell","sg13g2_io")]
        for model in models:
            if not model.is_file():p.error(f"Missing IHP model: {model}")
        files += [args.netlist,*models]
        if args.provenance:
            provenance=json.loads(args.provenance.read_text())
            if provenance.get("commit")!=commit:p.error("Netlist provenance commit differs from checkout HEAD")
    for mode in modes:
        simulator="verilator" if mode=="rtl" else "iverilog"
        if not shutil.which(simulator):p.error(f"Missing simulator: {simulator}")
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    simulator_versions={mode:subprocess.check_output(["verilator","--version"] if mode=="rtl" else ["iverilog","-V"],text=True,stderr=subprocess.DEVNULL).splitlines()[0] for mode in modes}
    summary=dict(commit=commit,started_utc=datetime.now(timezone.utc).isoformat(),
                 tools=dict(python=platform.python_version(),cocotb=version("cocotb"),simulators=simulator_versions),
                 configuration={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
                 netlist_provenance=provenance,source_sha256={str(f):sha(f) for f in files},modes={},comparison={})
    failed=False
    for mode in modes:
        directory=output/mode;directory.mkdir(exist_ok=True)
        xml=directory/"results.xml";xml.unlink(missing_ok=True)
        # Remove only generated observations in this mode, so stale results
        # cannot make a new filtered or failing run appear equivalent.
        for old in directory.glob("*.observations.json"):old.unlink()
        env=os.environ|dict(HEPIA_GL_MODE=mode,HEPIA_GL_CLOCK_NS=str(args.clock_ns),
            HEPIA_GL_I2C_DIV=str(args.i2c_quarter_cycles),HEPIA_OUTPUT=str(directory),
            HEPIA_TRACE={"quiet":"quiet","transactions":"instructions","pins":"cycles"}[args.trace],
            HEPIA_PROTOCOL=str(int(args.protocol)),HEPIA_FILTER_B64=base64.b64encode(args.test.encode()).decode(),
            COCOTB_TEST_FILTER="",COCOTB_TESTCASE="")
        command=["make","-f",str(HERE/"Makefile"),f"MODE={mode}",
                 f"SIM={'verilator' if mode=='rtl' else 'icarus'}",f"COCOTB_RESULTS_FILE={xml}"]
        if mode=="gl":command += [f"GL_NETLIST={args.netlist}",f"PDK_ROOT={args.pdk_root}"]
        print(f"Running {mode}: {directory/'sim.log'}",flush=True)
        with (directory/"sim.log").open("w") as log:
            result=subprocess.run(command,cwd=HERE,env=env,stdout=log,stderr=subprocess.STDOUT)
        cases=[]
        if xml.exists():
            for node in ET.parse(xml).iter("testcase"):
                status="fail" if node.find("failure") is not None or node.find("error") is not None else "skip" if node.find("skipped") is not None else "pass"
                cases.append(dict(name=node.get("name"),status=status))
        counts={key:sum(c["status"]==key for c in cases) for key in ("pass","fail","skip")}
        infrastructure_error=not (counts["pass"] or counts["fail"]) or (result.returncode!=0 and not counts["fail"])
        failed |= bool(counts["fail"] or infrastructure_error)
        summary["modes"][mode]=dict(cases=cases,counts=counts,infrastructure_error=infrastructure_error,returncode=result.returncode)
        (output/"summary.json").write_text(json.dumps(summary,indent=2))
        print(f"{mode}: {counts}; infrastructure_error={infrastructure_error}",flush=True)
    if args.mode=="both":
        passed={mode:{c["name"] for c in summary["modes"][mode]["cases"] if c["status"]=="pass"} for mode in modes}
        for name in sorted(passed["rtl"]&passed["gl"]):
            paths=[output/mode/(name+".observations.json") for mode in modes]
            equal=all(path.is_file() for path in paths) and paths[0].read_bytes()==paths[1].read_bytes()
            summary["comparison"][name]="identical" if equal else "different_or_missing"
            failed |= not equal
        if passed["rtl"]!=passed["gl"]:failed=True
    (output/"summary.json").write_text(json.dumps(summary,indent=2))
    return int(failed)


if __name__=="__main__":sys.exit(main())
