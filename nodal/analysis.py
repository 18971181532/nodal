"""Analyses: operating point, DC sweep, transient and AC small-signal.

Newton-Raphson with SPICE junction limiting solves the nonlinear DC /
transient systems; AC linearises every device around the operating point
and sweeps a complex MNA system over frequency.
"""

import cmath
import math

from . import devices
from .matrix import lu_solve, SingularMatrixError
from .mna import System


class AnalysisError(ValueError):
    pass


def newton(system, mode, dt=None, state=None, t=None, method="trap",
           overrides=None, warm=None, options=None, trace=None):
    """One nonlinear solve.  Returns (x, iterations, converged)."""
    opts = options or {}
    reltol = opts.get("reltol", 1e-3)
    abstol = opts.get("abstol", 1e-12)
    voltol = opts.get("voltol", 1e-6)
    maxiter = int(opts.get("maxiter", 100))

    diode_v = dict(warm or {})
    x = None
    iterations = 0
    for it in range(maxiter):
        a, b, diodes = system.build(mode, dt=dt, state=state, t=t,
                                    diode_v=diode_v, method=method,
                                    overrides=overrides)
        x = lu_solve(a, b)
        iterations = it + 1
        if not diodes:
            if trace is not None:
                trace.append({"iter": iterations, "dv": 0.0, "di": 0.0})
            return x, iterations, True
        dv_max, di_max = 0.0, 0.0
        new_v = {}
        for d in diodes:
            vd_new = system.diode_voltage(x, d)
            vd_old = d["vd"]
            limited = devices.diode_limit(vd_new, vd_old, d["model"])
            new_v[d["name"]] = limited
            dv_max = max(dv_max, abs(limited - vd_old))
            i_new = devices.diode_current(limited, d["model"])
            i_old = devices.diode_current(vd_old, d["model"])
            di_max = max(di_max, abs(i_new - i_old))
        if trace is not None:
            trace.append({"iter": iterations, "dv": dv_max, "di": di_max})
        converged = (dv_max < max(voltol, reltol * max(
            abs(v) for v in new_v.values())) and
            di_max < max(abstol, reltol * max(
                abs(devices.diode_current(v, d["model"]))
                for d, v in ((d, new_v[d["name"]]) for d in diodes))))
        diode_v = new_v
        if converged:
            # re-solve at the converged junction voltages for consistency
            a, b, _ = system.build(mode, dt=dt, state=state, t=t,
                                   diode_v=diode_v, method=method,
                                   overrides=overrides)
            x = lu_solve(a, b)
            return x, iterations, True
    return x, iterations, False


def operating_point(net, trace=None):
    system = System(net)
    try:
        x, iterations, ok = newton(system, "op", options=net.options,
                                   trace=trace)
    except SingularMatrixError as exc:
        raise AnalysisError(str(exc))
    if not ok:
        raise AnalysisError("operating point failed to converge after "
                            "%d iterations" % iterations)
    return {"system": system, "x": x, "iterations": iterations,
            "voltages": system.voltages(x),
            "currents": {el["name"]: x[system.branch(el["name"])]
                         for el in system.branch_elems}}


def dc_sweep(net, source, start, stop, step):
    system = System(net)
    src = source.lower()
    if not any(el["name"].lower() == src and el["kind"] in ("V", "I")
               for el in net.elements):
        raise AnalysisError("unknown sweep source %r" % source)
    points = []
    value = start
    warm = {}
    n_steps = int(round((stop - start) / step))
    for i in range(n_steps + 1):
        value = start + i * step
        x, _, ok = newton(system, "dc", overrides={src: value}, warm=warm,
                          options=net.options)
        if not ok:
            raise AnalysisError("DC sweep failed at %s = %g" % (source, value))
        warm = {d["name"]: system.diode_voltage(x, d)
                for d in system.build("dc", diode_v=warm,
                                      overrides={src: value})[2]}
        points.append({"source": value, "x": list(x)})
    return {"system": system, "source": source, "points": points}


def transient(net, tstep, tstop, tstart=0.0, tmax=None, uic=False,
              method="trap", max_points=20000):
    system = System(net)
    dt = min(tmax or tstep, tstep)
    if dt <= 0:
        raise AnalysisError("transient step must be positive")
    if tstop / dt > max_points:
        raise AnalysisError("transient would need %d points (limit %d); "
                            "increase tstep" % (int(tstop / dt), max_points))
    state = {}
    warm = {}
    if uic:
        x = [0.0] * system.size
    else:
        try:
            x, _, ok = newton(system, "op", options=net.options)
        except SingularMatrixError as exc:
            raise AnalysisError(str(exc))
        if not ok:
            raise AnalysisError("initial operating point did not converge")
        # initialise history from the operating point
        for el in net.elements:
            if el["kind"] in ("C", "L"):
                state[el["name"]] = {"v": 0.0, "i": 0.0}
        a, b, diodes = system.build("tran", dt=dt, state=state, t=0.0,
                                    method=method)
        # capacitor voltages / inductor currents at t=0
        for el in net.elements:
            if el["kind"] == "C":
                n1, n2 = system.idx(el["nodes"][0]), system.idx(el["nodes"][1])
                state[el["name"]]["v"] = ((x[n1] if n1 >= 0 else 0.0) -
                                          (x[n2] if n2 >= 0 else 0.0))
            elif el["kind"] == "L":
                state[el["name"]]["i"] = x[system.branch(el["name"])]
        warm = {d["name"]: system.diode_voltage(x, d) for d in diodes}

    times, rows = [0.0], [list(x)]
    t = 0.0
    retries = 0
    while t < tstop - 1e-15:
        step = min(dt, tstop - t)
        t_next = t + step
        try:
            x_new, _, ok = newton(system, "tran", dt=step, state=state,
                                  t=t_next, method=method, warm=warm,
                                  options=net.options)
        except SingularMatrixError as exc:
            raise AnalysisError(str(exc))
        if not ok:
            if step <= dt / 64.0:
                raise AnalysisError("transient failed to converge at t=%g"
                                    % t_next)
            dt = step / 2.0
            retries += 1
            continue
        system.update_tran_state(x_new, state, method)
        warm = {el["name"]: system.diode_voltage(
            x_new, {"n1": system.idx(el["nodes"][0]),
                    "n2": system.idx(el["nodes"][1])})
            for el in net.elements if el["kind"] == "D"}
        t = t_next
        x = x_new
        if t >= tstart - 1e-15:
            times.append(t)
            rows.append(list(x))
        # slowly restore the nominal step after successful retries
        if retries and dt < (tmax or tstep):
            dt = min(dt * 1.5, tmax or tstep)
    return {"system": system, "times": times, "rows": rows,
            "method": method, "retries": retries}


def _frequencies(mode, n, fstart, fstop):
    if mode == "lin":
        if n < 2:
            return [fstart]
        return [fstart + (fstop - fstart) * i / (n - 1) for i in range(n)]
    if fstop == fstart:
        return [fstart]
    decades = (math.log10(fstop / fstart) if mode == "dec"
               else math.log2(fstop / fstart))
    total = max(1, int(round(decades * n)))
    ratio = (fstop / fstart) ** (1.0 / total)
    return [fstart * ratio ** i for i in range(total + 1)]


def ac_sweep(net, mode, n, fstart, fstop):
    op = operating_point(net)
    system = op["system"]
    diode_v = {}
    for el in net.elements:
        if el["kind"] == "D":
            n1, n2 = system.idx(el["nodes"][0]), system.idx(el["nodes"][1])
            diode_v[el["name"]] = ((op["x"][n1] if n1 >= 0 else 0.0) -
                                   (op["x"][n2] if n2 >= 0 else 0.0))
    freqs = _frequencies(mode, n, fstart, fstop)
    rows = []
    for f in freqs:
        omega = 2.0 * math.pi * f
        a, b, _ = system.build("ac", omega=omega, diode_v=diode_v)
        rows.append(lu_solve(a, b))
    return {"system": system, "freqs": freqs, "rows": rows,
            "op": op["voltages"]}


def run_netlist(net):
    """Execute every analysis command in the netlist, in order."""
    results = []
    for spec in net.analyses:
        kind = spec["kind"]
        if kind == "op":
            results.append({"analysis": "op", **_serialise_op(
                operating_point(net))})
        elif kind == "dc":
            results.append({"analysis": "dc", **_serialise_dc(dc_sweep(
                net, spec["source"], spec["start"], spec["stop"],
                spec["step"]))})
        elif kind == "tran":
            results.append({"analysis": "tran", **_serialise_tran(transient(
                net, spec["tstep"], spec["tstop"],
                spec.get("tstart", 0.0), spec.get("tmax"),
                spec.get("uic", False)))})
        elif kind == "ac":
            results.append({"analysis": "ac", **_serialise_ac(ac_sweep(
                net, spec["mode"], spec["n"], spec["fstart"],
                spec["fstop"]))})
    return results


# ---------------------------------------------------------------- JSON views

def _serialise_op(op):
    return {"voltages": op["voltages"], "currents": op["currents"],
            "iterations": op["iterations"]}


def _select(system, rows, outputs):
    """Project solution rows onto v(node)/i(source) traces."""
    traces = {}
    if outputs:
        cols = []
        for kind, name in outputs:
            if kind == "v":
                if name == "0":
                    cols.append(("v(0)", None))
                else:
                    cols.append(("v(%s)" % name, system.node_index[name]))
            else:
                cols.append(("i(%s)" % name, system.branch(name)))
    else:
        cols = [("v(%s)" % n, i) for n, i in system.node_index.items()]
    for label, col in cols:
        traces[label] = [(row[col] if col is not None else 0.0)
                         for row in rows]
    return traces


def _serialise_tran(tr, outputs=None):
    system = tr["system"]
    return {"times": tr["times"], "method": tr["method"],
            "retries": tr["retries"],
            "traces": _select(system, tr["rows"], outputs)}


def _serialise_dc(dc, outputs=None):
    system = dc["system"]
    return {"source": dc["source"],
            "sweep": [p["source"] for p in dc["points"]],
            "traces": _select(system, [p["x"] for p in dc["points"]],
                              outputs)}


def _serialise_ac(ac, outputs=None):
    system = ac["system"]
    if outputs:
        cols = []
        for kind, name in outputs:
            if kind == "v":
                cols.append(("v(%s)" % name,
                             None if name == "0" else system.node_index[name]))
            else:
                cols.append(("i(%s)" % name, system.branch(name)))
    else:
        cols = [("v(%s)" % n, i) for n, i in system.node_index.items()]
    traces = {}
    for label, col in cols:
        vals = [(row[col] if col is not None else 0j) for row in ac["rows"]]
        traces[label] = {
            "mag": [abs(v) for v in vals],
            "db": [20.0 * math.log10(abs(v)) if abs(v) > 1e-300 else -600.0
                   for v in vals],
            "phase": [math.degrees(cmath.phase(v)) for v in vals],
        }
    return {"freqs": ac["freqs"], "traces": traces}
