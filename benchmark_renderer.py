#!/usr/bin/env python3
"""Repeatable local performance baseline for the legacy pixel renderer.

Run: python benchmark_renderer.py --repeats 3
Measurements are machine-specific and are not claims of Mac M1 performance.
"""
import argparse
import json
import statistics
import time
from volume_editor import Block, render_scene


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    b=Block(w=72,d=42,h=55,rise=15)
    edits=[dict(block=0,wall='front',t0=.16,t1=.83,z0=6,z1=49,
                depth=-10,columns=4,column_style=2)]
    report={}
    for angle in (0,45,135,225,315,345):
        durations=[]
        for _ in range(max(1,args.repeats)):
            t=time.perf_counter()
            render_scene([b],angle=angle,wall_edits=edits)
            durations.append((time.perf_counter()-t)*1000)
        report[str(angle)]={'median_ms':round(statistics.median(durations),2),
                            'min_ms':round(min(durations),2)}
    print(json.dumps(report,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
