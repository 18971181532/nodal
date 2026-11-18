"""Data views for the workbench: MNA heatmaps, Newton traces, benchmarks.

Everything here returns plain JSON-able structures; drawing happens in
the browser (Canvas) or the CLI.
"""

import math
import time

from . import analysis
from .mna import System
from .netlist import parse


def matrix_view(net, mode="op"):
    """The stamped MNA matrix with labels, ready for a heatmap."""
    system = System(net)
    if mode == "ac":
        a, b, _ = system.build("ac", omega=2.0 * math.pi * 1e3)
        values = [[abs(v) for v in row] for row in a]
        rhs = [abs(v) for v in b]
    else:
        a, b, _ = system.build(mode)
        values, rhs = a, b
    peak = max((abs(v) for row in values for v in row), default=0.0)
    peak = max(peak, max((abs(v) for v in rhs), default=0.0), 1e-30)
    # log-compressed magnitude so 1e5 gain and 1e-3 conductance coexist
    cells = [[math.log10(abs(v) / peak + 1e-12) / 12.0 + 1.0 if v else 0.0
              for v in row] for row in values]
    nz = sum(1 for row in values for v in row if v)
    return {"labels": system.labels, "values": values, "rhs": rhs,
            "cells": cells, "size": system.size,
            "nonzeros": nz,
            "density": nz / (system.size * system.size) if system.size else 0}


def newton_report(net):
    """Operating-point solve with a full iteration trace."""
    trace = []
    op = analysis.operating_point(net, trace=trace)
    return {"iterations": op["iterations"], "trace": trace,
            "voltages": op["voltages"], "currents": op["currents"]}


def downsample(times, traces, limit=1200):
    """Uniform decimation for plotting large transient records."""
    n = len(times)
    if n <= limit:
        return {"times": times, "traces": traces}
    stride = math.ceil(n / limit)
    idx = list(range(0, n, stride))
    if idx[-1] != n - 1:
        idx.append(n - 1)
    return {"times": [times[i] for i in idx],
            "traces": {k: [v[i] for i in idx] for k, v in traces.items()}}


def _ladder(n):
    """Generate an n-stage RC ladder netlist for benchmarking."""
    lines = ["rc ladder %d stages" % n, "V1 in 0 DC 1 AC 1"]
    for i in range(n):
        a = "in" if i == 0 else "n%d" % i
        b = "n%d" % (i + 1)
        lines.append("R%d %s %s 1k" % (i + 1, a, b))
        lines.append("C%d %s 0 1n" % (i + 1, b))
    lines.append(".end")
    return "\n".join(lines)


def bench(stages=24, tran_points=400, ac_points=60):
    """Time each analysis on a generated RC ladder (pure Python)."""
    net = parse(_ladder(stages))
    t0 = time.perf_counter()
    op = analysis.operating_point(net)
    op_ms = (time.perf_counter() - t0) * 1e3

    tstep = 1e-6
    t0 = time.perf_counter()
    tr = analysis.transient(net, tstep, tstep * tran_points)
    tran_ms = (time.perf_counter() - t0) * 1e3

    t0 = time.perf_counter()
    ac = analysis.ac_sweep(net, "dec", max(1, ac_points // 4), 1e2, 1e6)
    ac_ms = (time.perf_counter() - t0) * 1e3

    system = op["system"]
    return {
        "stages": stages, "matrix_size": system.size,
        "op_ms": round(op_ms, 2),
        "tran_ms": round(tran_ms, 2),
        "tran_points": len(tr["times"]),
        "tran_ms_per_point": round(tran_ms / max(1, len(tr["times"])), 3),
        "ac_ms": round(ac_ms, 2),
        "ac_points": len(ac["freqs"]),
        "ac_ms_per_point": round(ac_ms / max(1, len(ac["freqs"])), 3),
    }


EXAMPLES = {
    "divider": """resistive divider
V1 in 0 DC 10
R1 in mid 2k
R2 mid 0 3k
.op
.end
""",
    "rc": """RC step response
V1 in 0 PULSE(0 5 0 1n 1n 10m 20m)
R1 in out 1k
C1 out 0 1u
.tran 10u 5m
.end
""",
    "rlc": """RLC bandpass
V1 in 0 DC 0 AC 1
R1 in mid 10
L1 mid out 1m
C1 out 0 1u
R2 out 0 1k
.ac dec 40 100 1meg
.end
""",
    "rectifier": """half-wave rectifier
V1 in 0 SIN(0 5 1k)
D1 in out DIDEAL
R1 out 0 1k
C1 out 0 10u
.model DIDEAL D(IS=1e-14 N=1)
.tran 20u 5m
.end
""",
    "tia": """photodiode transimpedance amplifier
* photodiode = 2uA signal pulse + 3pF junction capacitance
I1 0 sum PULSE(0 2u 1u 10n 10n 20u 40u)
C1 sum 0 3p
* op-amp macromodel: VCVS, gain 1e5, single pole at 100 kHz
E1 amp 0 sum 0 -1e5
R3 amp out 100
C2 out 0 15.9n
Rf out sum 100k
Cf out sum 0.5p
.tran 50n 40u
.end
""",
}
