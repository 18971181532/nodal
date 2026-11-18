import math
import unittest

from nodal import analysis, measure, visual
from nodal.netlist import parse


class TestOperatingPoint(unittest.TestCase):
    def test_divider(self):
        op = analysis.operating_point(parse(visual.EXAMPLES["divider"]))
        self.assertAlmostEqual(op["voltages"]["mid"], 6.0, places=9)
        self.assertAlmostEqual(op["currents"]["V1"], -10.0 / 5000.0,
                               places=9)

    def test_diode_series_resistor(self):
        net = parse("""t
V1 in 0 5
R1 in out 1k
D1 out 0 DM
.model DM D(IS=1e-14 N=1)
.op
.end
""")
        op = analysis.operating_point(net)
        vd = op["voltages"]["out"]
        # KCL: (5 - vd)/1k = IS (exp(vd/VT) - 1)
        from nodal.devices import diode_current
        lhs = (5.0 - vd) / 1000.0
        rhs = diode_current(vd, {"IS": 1e-14, "N": 1.0})
        self.assertAlmostEqual(lhs / rhs, 1.0, places=4)
        self.assertGreater(vd, 0.5)
        self.assertLess(vd, 0.8)

    def test_floating_node_raises(self):
        net = parse("t\nV1 a 0 1\nR1 a b 1k\n.op\n.end\n")
        # node b only connects through R1 to a driven node: still solvable
        op = analysis.operating_point(net)
        self.assertAlmostEqual(op["voltages"]["b"], 1.0)

    def test_singular_raises(self):
        net = parse("t\nI1 a 0 1m\nI2 a 0 1m\n.op\n.end\n")
        with self.assertRaises(analysis.AnalysisError):
            analysis.operating_point(net)


class TestDcSweep(unittest.TestCase):
    def test_diode_iv(self):
        net = parse("""t
V1 a 0 0
D1 a 0 DM
.model DM D(IS=1e-14 N=1)
.dc V1 0.3 0.7 0.05
.print dc i(V1)
.end
""")
        dc = analysis.dc_sweep(net, "V1", 0.3, 0.7, 0.05)
        obj = analysis._serialise_dc(dc, [("i", "v1")])
        currents = obj["traces"]["i(v1)"]
        self.assertEqual(len(currents), 9)
        # magnitude grows roughly x10 per ~60 mV
        self.assertGreater(abs(currents[-1]) / abs(currents[-3]), 5.0)
        self.assertLess(abs(currents[0]), 1e-4)

    def test_unknown_source(self):
        net = parse(visual.EXAMPLES["divider"])
        with self.assertRaises(analysis.AnalysisError):
            analysis.dc_sweep(net, "V9", 0, 1, 0.1)


class TestTransient(unittest.TestCase):
    def test_rc_step_matches_analytic(self):
        net = parse(visual.EXAMPLES["rc"])
        tr = analysis.transient(net, 1e-5, 5e-3)
        obj = analysis._serialise_tran(tr)
        times, v = obj["times"], obj["traces"]["v(out)"]
        for target in (0.5e-3, 1e-3, 2e-3, 3e-3):
            i = min(range(len(times)), key=lambda k: abs(times[k] - target))
            exact = 5.0 * (1.0 - math.exp(-times[i] / 1e-3))
            self.assertLess(abs(v[i] - exact) / max(exact, 0.1), 0.01)

    def test_be_also_stable(self):
        net = parse(visual.EXAMPLES["rc"])
        tr = analysis.transient(net, 1e-5, 5e-3, method="be")
        obj = analysis._serialise_tran(tr)
        self.assertAlmostEqual(obj["traces"]["v(out)"][-1], 5.0, delta=0.05)

    def test_uic_starts_at_zero(self):
        net = parse("t\nV1 a 0 5\nR1 a b 1k\nC1 b 0 1u\n.tran 1u 1m\n.end\n")
        tr = analysis.transient(net, 1e-6, 5e-3, uic=True)
        obj = analysis._serialise_tran(tr)
        self.assertEqual(obj["traces"]["v(b)"][0], 0.0)
        self.assertAlmostEqual(obj["traces"]["v(b)"][-1], 5.0, delta=0.05)

    def test_rlc_rings(self):
        net = parse("""t
V1 in 0 PULSE(0 1 0 1n 1n 10m 20m)
L1 in out 1m
C1 out 0 1u
R1 out 0 100
.tran 1u 2m
.end
""")
        tr = analysis.transient(net, 1e-6, 2e-3)
        obj = analysis._serialise_tran(tr)
        v = obj["traces"]["v(out)"]
        self.assertGreater(max(v), 1.3)          # underdamped overshoot
        self.assertAlmostEqual(measure.final_value(obj["times"], v), 1.0,
                               places=2)

    def test_rectifier_charges_cap(self):
        net = parse(visual.EXAMPLES["rectifier"])
        tr = analysis.transient(net, 2e-5, 5e-3)
        obj = analysis._serialise_tran(tr)
        v = obj["traces"]["v(out)"]
        plateau = measure.final_value(obj["times"], v)
        self.assertGreater(plateau, 3.5)
        self.assertLess(plateau, 4.6)
        self.assertLess(measure.ripple(v), 0.8)

    def test_tia_gain(self):
        net = parse(visual.EXAMPLES["tia"])
        tr = analysis.transient(net, 5e-8, 4e-5)
        obj = analysis._serialise_tran(tr)
        pairs = [(t, v) for t, v in zip(obj["times"],
                                        obj["traces"]["v(out)"])
                 if 10e-6 < t < 19e-6]
        plateau = sum(v for _, v in pairs) / len(pairs)
        self.assertAlmostEqual(plateau, -0.2, places=3)

    def test_too_many_points(self):
        net = parse(visual.EXAMPLES["rc"])
        with self.assertRaises(analysis.AnalysisError):
            analysis.transient(net, 1e-9, 1.0)


class TestAc(unittest.TestCase):
    def test_rc_lowpass(self):
        net = parse("""t
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 1u
.ac dec 40 1 1meg
.end
""")
        ac = analysis.ac_sweep(net, "dec", 80, 1, 1e6)
        obj = analysis._serialise_ac(ac)
        data = obj["traces"]["v(out)"]
        self.assertAlmostEqual(data["db"][0], 0.0, places=3)
        fc = 1.0 / (2 * math.pi * 1e-3)
        bw = measure.bandwidth(obj["freqs"], data["db"])
        self.assertLess(abs(bw - fc) / fc, 0.03)
        # phase approaches -90 deg at high frequency
        self.assertLess(data["phase"][-1], -85.0)

    def test_rlc_resonance(self):
        net = parse(visual.EXAMPLES["rlc"])
        ac = analysis.ac_sweep(net, "dec", 40, 100, 1e6)
        obj = analysis._serialise_ac(ac)
        pk = measure.peak_gain(obj["freqs"],
                               obj["traces"]["v(out)"]["db"])
        f0 = 1.0 / (2 * math.pi * math.sqrt(1e-3 * 1e-6))
        self.assertLess(abs(pk["freq"] - f0) / f0, 0.03)

    def test_oct_lin_modes(self):
        net = parse(visual.EXAMPLES["rlc"])
        for mode in ("oct", "lin"):
            ac = analysis.ac_sweep(net, mode, 10, 100, 1e4)
            self.assertGreater(len(ac["freqs"]), 2)
            self.assertAlmostEqual(ac["freqs"][0], 100)
            self.assertAlmostEqual(ac["freqs"][-1], 1e4, places=3)


class TestRunNetlist(unittest.TestCase):
    def test_run_all(self):
        net = parse("""t
V1 in 0 DC 5 AC 1
R1 in out 1k
C1 out 0 1u
.op
.tran 10u 1m
.ac dec 10 10 100k
.dc V1 0 5 1
.end
""")
        results = analysis.run_netlist(net)
        self.assertEqual([r["analysis"] for r in results],
                         ["op", "tran", "ac", "dc"])
        self.assertAlmostEqual(results[0]["voltages"]["out"], 5.0)


if __name__ == "__main__":
    unittest.main()
