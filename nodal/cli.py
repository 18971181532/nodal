"""Nodal command line interface.

Every subcommand supports --json for machine-readable output; errors
print to stderr and return exit code 2.
"""

import argparse
import json
import sys

from . import __version__, analysis, measure, visual
from .netlist import NetlistError, parse, parse_value


def _load(args):
    with open(args.file, "r", encoding="utf-8") as fh:
        return parse(fh.read())


def _emit(args, obj, text=None):
    if args.json:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    elif text is not None:
        print(text)


def _fmt(v):
    if isinstance(v, float):
        return "%.6g" % v
    return str(v)


def cmd_parse(args):
    net = _load(args)
    info = {"title": net.title,
            "elements": [{"name": el["name"], "kind": el["kind"],
                          "nodes": el["nodes"]} for el in net.elements],
            "nodes": net.node_names(),
            "models": net.models,
            "analyses": net.analyses,
            "outputs": net.outputs}
    lines = ["%s" % net.title,
             "%d elements, %d nodes (plus ground)" %
             (len(net.elements), len(net.node_names()))]
    for el in net.elements:
        lines.append("  %-6s %-2s %s" % (el["name"], el["kind"],
                                         " ".join(el["nodes"])))
    for spec in net.analyses:
        lines.append("  analysis: %s" % spec)
    _emit(args, info, "\n".join(lines))


def cmd_op(args):
    net = _load(args)
    op = analysis.operating_point(net)
    obj = {"voltages": op["voltages"], "currents": op["currents"],
           "iterations": op["iterations"]}
    lines = ["operating point (%d Newton iterations)" % op["iterations"]]
    for name, v in op["voltages"].items():
        lines.append("  v(%s) = %s V" % (name, _fmt(v)))
    for name, i in op["currents"].items():
        lines.append("  i(%s) = %s A" % (name, _fmt(i)))
    _emit(args, obj, "\n".join(lines))


def cmd_dc(args):
    net = _load(args)
    spec = next((a for a in net.analyses if a["kind"] == "dc"), None)
    source = args.source or (spec and spec["source"])
    start = args.start if args.start is not None else (spec and spec["start"])
    stop = args.stop if args.stop is not None else (spec and spec["stop"])
    step = args.step if args.step is not None else (spec and spec["step"])
    if source is None or start is None or stop is None or step is None:
        raise SystemExit("dc needs --source --start --stop --step "
                         "(or a .dc line in the netlist)")
    dc = analysis.dc_sweep(net, source, start, stop, step)
    obj = analysis._serialise_dc(dc, net.outputs or None)
    lines = ["DC sweep %s: %g -> %g, %d points" %
             (source, start, stop, len(obj["sweep"]))]
    for label, values in obj["traces"].items():
        lines.append("  %s: %s ... %s" % (label, _fmt(values[0]),
                                          _fmt(values[-1])))
    _emit(args, obj, "\n".join(lines))


def cmd_tran(args):
    net = _load(args)
    spec = next((a for a in net.analyses if a["kind"] == "tran"), None)
    tstep = args.step if args.step is not None else (spec and spec["tstep"])
    tstop = args.stop if args.stop is not None else (spec and spec["tstop"])
    if tstep is None or tstop is None:
        raise SystemExit("tran needs --step --stop (or a .tran line)")
    tr = analysis.transient(net, tstep, tstop,
                            tstart=(spec or {}).get("tstart", 0.0),
                            tmax=args.max_step or (spec or {}).get("tmax"),
                            uic=args.uic or (spec or {}).get("uic", False),
                            method=args.method)
    obj = analysis._serialise_tran(tr, net.outputs or None)
    obj["summary"] = measure.summarise_tran(obj["times"], obj["traces"])
    lines = ["transient (%s): %d points, %d step retries" %
             (args.method, len(obj["times"]), tr["retries"])]
    for label, s in obj["summary"].items():
        lines.append("  %s: min %s  max %s  final %s" %
                     (label, _fmt(s["min"]), _fmt(s["max"]),
                      _fmt(s["final"])))
    _emit(args, obj, "\n".join(lines))


def cmd_ac(args):
    net = _load(args)
    spec = next((a for a in net.analyses if a["kind"] == "ac"), None)
    mode = args.mode or (spec and spec["mode"]) or "dec"
    n = args.n or (spec and spec["n"]) or 20
    fstart = args.start if args.start is not None else (
        spec and spec["fstart"]) or 1.0
    fstop = args.stop if args.stop is not None else (
        spec and spec["fstop"]) or 1e6
    ac = analysis.ac_sweep(net, mode, n, fstart, fstop)
    obj = analysis._serialise_ac(ac, net.outputs or None)
    obj["summary"] = measure.summarise_ac(obj["freqs"], obj["traces"])
    lines = ["AC sweep %s: %d points, %g Hz -> %g Hz" %
             (mode, len(obj["freqs"]), fstart, fstop)]
    for label, s in obj["summary"].items():
        bw = s["bandwidth"]
        lines.append("  %s: DC gain %.2f dB, -3dB BW %s, peak %.2f dB @ %.4g Hz"
                     % (label, s["dc_gain_db"],
                        ("%.4g Hz" % bw) if bw else "beyond sweep",
                        s["peak"]["db"], s["peak"]["freq"]))
    _emit(args, obj, "\n".join(lines))


def cmd_run(args):
    net = _load(args)
    if not net.analyses:
        raise SystemExit("netlist contains no analysis commands")
    results = analysis.run_netlist(net)
    for res in results:
        if res["analysis"] == "tran":
            res["summary"] = measure.summarise_tran(res["times"],
                                                    res["traces"])
        elif res["analysis"] == "ac":
            res["summary"] = measure.summarise_ac(res["freqs"],
                                                  res["traces"])
    lines = []
    for res in results:
        kind = res["analysis"]
        if kind == "op":
            lines.append("op: " + ", ".join(
                "v(%s)=%s" % (k, _fmt(v)) for k, v in res["voltages"].items()))
        elif kind == "tran":
            lines.append("tran: %d points" % len(res["times"]))
        elif kind == "ac":
            lines.append("ac: %d frequencies" % len(res["freqs"]))
        elif kind == "dc":
            lines.append("dc: %d points" % len(res["sweep"]))
    _emit(args, {"results": results}, "\n".join(lines))


def cmd_matrix(args):
    net = _load(args)
    view = visual.matrix_view(net, args.mode)
    if args.json:
        print(json.dumps(view, ensure_ascii=False))
        return
    print("MNA matrix (%s): %dx%d, %d nonzeros (%.1f%% dense)" %
          (args.mode, view["size"], view["size"], view["nonzeros"],
           view["density"] * 100))
    header = " " * 12 + " ".join("%10s" % l[:10] for l in view["labels"])
    print(header + " %10s" % "rhs")
    for label, row, rhs in zip(view["labels"], view["values"], view["rhs"]):
        print("%12s " % label[:12] +
              " ".join("%10.3g" % v for v in row) + " %10.3g" % rhs)


def cmd_newton(args):
    net = _load(args)
    report = visual.newton_report(net)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    print("Newton convergence: %d iterations" % report["iterations"])
    for step in report["trace"]:
        print("  iter %2d  max|dv| = %.3e  max|di| = %.3e" %
              (step["iter"], step["dv"], step["di"]))
    for name, v in report["voltages"].items():
        print("  v(%s) = %s" % (name, _fmt(v)))


def cmd_bench(args):
    result = visual.bench(args.stages, args.points, args.ac_points)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("RC ladder: %d stages, matrix %dx%d" %
          (result["stages"], result["matrix_size"], result["matrix_size"]))
    print("  op    %8.2f ms" % result["op_ms"])
    print("  tran  %8.2f ms (%d points, %.3f ms/point)" %
          (result["tran_ms"], result["tran_points"],
           result["tran_ms_per_point"]))
    print("  ac    %8.2f ms (%d points, %.3f ms/point)" %
          (result["ac_ms"], result["ac_points"], result["ac_ms_per_point"]))


def cmd_serve(args):
    from .server import run
    run(port=args.port, open_browser=not args.no_open)


def build_parser():
    p = argparse.ArgumentParser(
        prog="nodal",
        description="Hand-written SPICE-style analog circuit simulator.")
    p.add_argument("--version", action="version",
                   version="nodal %s" % __version__)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name, help_text, func, need_file=True):
        sp = sub.add_parser(name, help=help_text)
        if need_file:
            sp.add_argument("file", help="netlist file (.cir)")
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(func=func)
        return sp

    add("parse", "parse and summarise a netlist", cmd_parse)
    add("op", "DC operating point (Newton-Raphson)", cmd_op)

    sp = add("dc", "DC sweep", cmd_dc)
    sp.add_argument("--source")
    sp.add_argument("--start", type=parse_value)
    sp.add_argument("--stop", type=parse_value)
    sp.add_argument("--step", type=parse_value)

    sp = add("tran", "transient analysis", cmd_tran)
    sp.add_argument("--step", type=parse_value)
    sp.add_argument("--stop", type=parse_value)
    sp.add_argument("--max-step", type=parse_value)
    sp.add_argument("--method", choices=("trap", "be"), default="trap")
    sp.add_argument("--uic", action="store_true")

    sp = add("ac", "AC small-signal sweep", cmd_ac)
    sp.add_argument("--mode", choices=("dec", "oct", "lin"))
    sp.add_argument("--n", type=int)
    sp.add_argument("--start", type=parse_value)
    sp.add_argument("--stop", type=parse_value)

    add("run", "execute all analyses in the netlist", cmd_run)

    sp = add("matrix", "show the stamped MNA matrix", cmd_matrix)
    sp.add_argument("--mode", choices=("op", "ac"), default="op")

    add("newton", "operating point with convergence trace", cmd_newton)

    sp = add("bench", "benchmark on a generated RC ladder", cmd_bench,
             need_file=False)
    sp.add_argument("--stages", type=int, default=24)
    sp.add_argument("--points", type=int, default=400)
    sp.add_argument("--ac-points", type=int, default=60)

    sp = add("serve", "launch the browser workbench", cmd_serve,
             need_file=False)
    sp.add_argument("--port", type=int, default=8863)
    sp.add_argument("--no-open", action="store_true")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (NetlistError, analysis.AnalysisError, ValueError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
