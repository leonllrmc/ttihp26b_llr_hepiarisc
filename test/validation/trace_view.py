#!/usr/bin/env python3
"""Render JSONL execution/protocol traces as a readable chronological log."""
import argparse
from collections import deque
import json
from pathlib import Path


def render(event):
    kind=event["kind"];time=event.get("time_ns",0)
    prefix=f"{time:13.1f} ns  "
    if kind=="instruction":
        before,after=event["before"],event["after"]
        changes=" ".join(f"R{i}:{a:02x}->{b:02x}" for i,(a,b) in enumerate(zip(before["regs"],after["regs"])) if a!=b)
        flags="".join(map(str,before["flags"]))+"->"+"".join(map(str,after["flags"]))
        text=f"{before['bank']:x}:{before['pc']:02x}  {event['assembly']:<30} => {after['bank']:x}:{after['pc']:02x}  NZCV={flags} SP={after['sp']} {changes}"
        irq=event.get("irq",before.get("irq",0))
        if irq:text+="  IRQ"
        if before.get("mem_write"):text+=f"  WRITE[{before['address']:02x}]={before['write_data']:02x}"
        if before.get("mem_read"):text+=f"  READ[{before['address']:02x}]={before['read_data']:02x}"
        return prefix+text
    if kind=="i2c_start":return prefix+("I2C repeated START" if event.get("repeated") else "I2C START")
    if kind=="i2c_stop":return prefix+"I2C STOP"
    if kind=="i2c_ack":return prefix+f"I2C {event['by']} "+("ACK" if event["ack"] else "NAK")
    if kind=="i2c_byte":return prefix+f"I2C {event['direction']} byte 0x{event['data']:02x}"
    if kind=="failure_context":
        return "--- buffered context ---\n"+"\n".join(render(e) for e in event["events"])+"\n--- end context ---"
    return prefix+kind+" "+json.dumps({k:v for k,v in event.items() if k not in ("kind","time_ns")})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("trace",type=Path)
    p.add_argument("--kind",action="append",help="Filter by event kind prefix; repeatable")
    p.add_argument("--tail",type=int,default=0,help="Show the last N matching events")
    args=p.parse_args()
    if args.tail<0:p.error("--tail must be nonnegative")
    lines=deque(maxlen=args.tail or None)
    for line in args.trace.open():
        event=json.loads(line)
        if args.kind and not any(event["kind"].startswith(k) for k in args.kind):continue
        text=render(event)
        if args.tail:lines.append(text)
        else:print(text)
    if args.tail:print("\n".join(lines))


if __name__=="__main__":main()
