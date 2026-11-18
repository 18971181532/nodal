"""Modified Nodal Analysis: unknowns, stamps and system assembly.

Unknown vector = [node voltages (ground excluded)] + [branch currents of
V sources, inductors, VCVS (E) and CCVS (H)].  Every element contributes a
small "stamp" to A and b; nonlinear devices are linearised around the
current Newton iterate by the caller (analysis.py).

Modes
    "op"/"dc" : capacitors open, inductors short
    "tran"    : capacitor / inductor companion models (BE or trapezoidal)
    "ac"      : complex admittances at angular frequency omega
"""

import cmath
import math

from . import devices


class System:
    def __init__(self, net):
        self.net = net
        self.node_names = net.node_names()
        self.node_index = {name: i for i, name in enumerate(self.node_names)}
        self.branch_elems = [el for el in net.elements
                             if el["kind"] in ("V", "L", "E", "H")]
        base = len(self.node_names)
        self.branch_index = {el["name"].lower(): base + i
                             for i, el in enumerate(self.branch_elems)}
        self.size = base + len(self.branch_elems)
        self.labels = (["v(%s)" % n for n in self.node_names] +
                       ["i(%s)" % el["name"] for el in self.branch_elems])

    def idx(self, node):
        return -1 if node == "0" else self.node_index[node]

    def branch(self, name):
        return self.branch_index[name.lower()]

    # ------------------------------------------------------------ stamps
    @staticmethod
    def stamp_g(a, i, j, g):
        if i >= 0:
            a[i][i] += g
        if j >= 0:
            a[j][j] += g
        if i >= 0 and j >= 0:
            a[i][j] -= g
            a[j][i] -= g

    @staticmethod
    def stamp_i(b, i, j, current):
        """Current `current` flows from node i to node j through the source."""
        if i >= 0:
            b[i] -= current
        if j >= 0:
            b[j] += current

    def stamp_v(self, a, b, k, i, j, value):
        if i >= 0:
            a[i][k] += 1
            a[k][i] += 1
        if j >= 0:
            a[j][k] -= 1
            a[k][j] -= 1
        b[k] += value

    # ------------------------------------------------------------ assembly
    def build(self, mode, dt=None, state=None, diode_v=None, t=None,
              omega=None, method="trap", overrides=None):
        """Assemble (A, b).  Returns also the list of diode linearisations.

        ``state``  : tran history {name: {...}} (created empty if None)
        ``diode_v``: {name: junction voltage} for the Newton iterate
        ``overrides``: {source name: value} for .dc sweeps
        """
        complex_mode = mode == "ac"
        zero = 0j if complex_mode else 0.0
        a = [[zero] * self.size for _ in range(self.size)]
        b = [zero] * self.size
        diodes = []
        overrides = overrides or {}

        for el in self.net.elements:
            kind = el["kind"]
            name = el["name"]
            n1, n2 = (self.idx(n) for n in el["nodes"][:2])

            if kind == "R":
                self.stamp_g(a, n1, n2, 1.0 / el["value"])

            elif kind == "I":
                if complex_mode:
                    mag, ph = el["ac"], math.radians(el["ac_phase"])
                    value = mag * cmath.exp(1j * ph)
                elif name.lower() in overrides:
                    value = overrides[name.lower()]
                else:
                    value = devices.source_value(el, t)
                self.stamp_i(b, n1, n2, value)

            elif kind == "V":
                k = self.branch(name)
                if complex_mode:
                    mag, ph = el["ac"], math.radians(el["ac_phase"])
                    value = mag * cmath.exp(1j * ph)
                elif name.lower() in overrides:
                    value = overrides[name.lower()]
                else:
                    value = devices.source_value(el, t)
                self.stamp_v(a, b, k, n1, n2, value)

            elif kind == "C":
                if mode in ("op", "dc"):
                    continue                      # open circuit
                if complex_mode:
                    self.stamp_g(a, n1, n2, 1j * omega * el["value"])
                else:
                    hist = state.setdefault(name, {"v": 0.0, "i": 0.0})
                    g = (2.0 if method == "trap" else 1.0) * el["value"] / dt
                    ieq = g * hist["v"] + (hist["i"] if method == "trap" else 0.0)
                    self.stamp_g(a, n1, n2, g)
                    # i_cap = g*v - ieq: the history source injects into n1
                    self.stamp_i(b, n1, n2, -ieq)
                    hist["_g"], hist["_ieq"] = g, ieq

            elif kind == "L":
                k = self.branch(name)
                # KCL contribution of the branch current
                if n1 >= 0:
                    a[n1][k] += 1
                if n2 >= 0:
                    a[n2][k] -= 1
                if n1 >= 0:
                    a[k][n1] += 1
                if n2 >= 0:
                    a[k][n2] -= 1
                if mode in ("op", "dc"):
                    pass                          # short: v = 0
                elif complex_mode:
                    a[k][k] -= 1j * omega * el["value"]
                else:
                    hist = state.setdefault(name, {"v": 0.0, "i": 0.0})
                    req = (2.0 if method == "trap" else 1.0) * el["value"] / dt
                    veq = -req * hist["i"] - (hist["v"] if method == "trap" else 0.0)
                    a[k][k] -= req
                    b[k] += veq

            elif kind == "D":
                model = self.net.models[el["model"]]
                vd = (diode_v or {}).get(name, 0.0)
                if complex_mode:
                    gd = devices.diode_conductance(vd, model)
                    self.stamp_g(a, n1, n2, gd)
                else:
                    gd = devices.diode_conductance(vd, model)
                    ie = devices.diode_current(vd, model)
                    ieq = ie - gd * vd
                    self.stamp_g(a, n1, n2, gd)
                    self.stamp_i(b, n1, n2, ieq)
                    diodes.append({"name": name, "n1": n1, "n2": n2,
                                   "vd": vd, "model": model})

            elif kind == "E":
                k = self.branch(name)
                c1, c2 = self.idx(el["nodes"][2]), self.idx(el["nodes"][3])
                if n1 >= 0:
                    a[n1][k] += 1
                    a[k][n1] += 1
                if n2 >= 0:
                    a[n2][k] -= 1
                    a[k][n2] -= 1
                if c1 >= 0:
                    a[k][c1] -= el["gain"]
                if c2 >= 0:
                    a[k][c2] += el["gain"]

            elif kind == "G":
                c1, c2 = self.idx(el["nodes"][2]), self.idx(el["nodes"][3])
                g = el["gain"]
                if n1 >= 0 and c1 >= 0:
                    a[n1][c1] += g
                if n1 >= 0 and c2 >= 0:
                    a[n1][c2] -= g
                if n2 >= 0 and c1 >= 0:
                    a[n2][c1] -= g
                if n2 >= 0 and c2 >= 0:
                    a[n2][c2] += g

            elif kind == "F":
                kc = self.branch(el["control"])
                if n1 >= 0:
                    a[n1][kc] += el["gain"]
                if n2 >= 0:
                    a[n2][kc] -= el["gain"]

            elif kind == "H":
                k = self.branch(name)
                kc = self.branch(el["control"])
                if n1 >= 0:
                    a[n1][k] += 1
                    a[k][n1] += 1
                if n2 >= 0:
                    a[n2][k] -= 1
                    a[k][n2] -= 1
                a[k][kc] -= el["gain"]

        return a, b, diodes

    # ------------------------------------------------------------ helpers
    def voltages(self, x):
        return {name: x[i] for name, i in self.node_index.items()}

    def branch_current(self, x, name):
        return x[self.branch(name)]

    def diode_voltage(self, x, diode):
        v1 = x[diode["n1"]] if diode["n1"] >= 0 else 0.0
        v2 = x[diode["n2"]] if diode["n2"] >= 0 else 0.0
        return v1 - v2

    def update_tran_state(self, x, state, method):
        """Advance capacitor / inductor history after a converged step."""
        for el in self.net.elements:
            if el["kind"] == "C":
                hist = state[el["name"]]
                n1, n2 = self.idx(el["nodes"][0]), self.idx(el["nodes"][1])
                v = (x[n1] if n1 >= 0 else 0.0) - (x[n2] if n2 >= 0 else 0.0)
                hist["i"] = hist["_g"] * v - hist["_ieq"]
                hist["v"] = v
            elif el["kind"] == "L":
                hist = state[el["name"]]
                n1, n2 = self.idx(el["nodes"][0]), self.idx(el["nodes"][1])
                hist["v"] = ((x[n1] if n1 >= 0 else 0.0) -
                             (x[n2] if n2 >= 0 else 0.0))
                hist["i"] = x[self.branch(el["name"])]
