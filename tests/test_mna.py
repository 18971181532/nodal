import unittest

from nodal.mna import System
from nodal.netlist import parse


class TestStamps(unittest.TestCase):
    def test_resistor_stamp(self):
        net = parse("t\nR1 a b 1k\nR2 b 0 1k\nV1 a 0 1\n.op\n.end\n")
        system = System(net)
        a, b, _ = system.build("op")
        # node a: 1e-3 on diagonal, -1e-3 to b
        ia, ib = system.node_index["a"], system.node_index["b"]
        self.assertAlmostEqual(a[ia][ia], 1e-3)
        self.assertAlmostEqual(a[ia][ib], -1e-3)
        self.assertAlmostEqual(a[ib][ib], 2e-3)

    def test_unknown_count(self):
        net = parse("t\nV1 a 0 1\nL1 a b 1m\nR1 b 0 1k\nE1 c 0 b 0 2\n"
                    ".op\n.end\n")
        system = System(net)
        # 3 nodes + V1 + L1 + E1 branch currents
        self.assertEqual(system.size, 6)
        self.assertEqual(system.labels[-1], "i(E1)")

    def test_cap_open_inductor_short_in_op(self):
        net = parse("t\nV1 a 0 5\nL1 a b 1m\nC1 b 0 1u\nR1 b 0 1k\n"
                    ".op\n.end\n")
        system = System(net)
        from nodal.matrix import lu_solve
        a, b, _ = system.build("op")
        x = lu_solve(a, b)
        self.assertAlmostEqual(system.voltages(x)["b"], 5.0)

    def test_ac_complex_admittance(self):
        net = parse("t\nV1 a 0 AC 1\nC1 a 0 1u\n.op\n.end\n")
        system = System(net)
        import math
        omega = 2 * math.pi * 1000
        a, b, _ = system.build("ac", omega=omega)
        ia = system.node_index["a"]
        self.assertAlmostEqual(a[ia][ia].imag, omega * 1e-6)

    def test_g_stamp(self):
        net = parse("t\nV1 in 0 1\nG1 out 0 in 0 1m\nR1 out 0 1k\n"
                    ".op\n.end\n")
        from nodal import analysis
        op = analysis.operating_point(net)
        # i = 1m * 1V through 1k -> v(out) = -1 V (current pulled from out)
        self.assertAlmostEqual(op["voltages"]["out"], -1.0)

    def test_f_h_stamps(self):
        net = parse("""t
V1 in 0 1
Vsense in mid 0
R1 mid 0 1k
F1 f 0 Vsense 2
R2 f 0 1k
H1 h 0 Vsense 500
R3 h 0 1k
.op
.end
""")
        from nodal import analysis
        op = analysis.operating_point(net)
        i_ctrl = op["currents"]["Vsense"]      # 1 mA
        self.assertAlmostEqual(i_ctrl, 1e-3, places=9)
        self.assertAlmostEqual(op["voltages"]["f"], -2e-3 * 1e3)
        self.assertAlmostEqual(op["voltages"]["h"], 0.5)

    def test_tran_companion_values(self):
        net = parse("t\nV1 a 0 1\nR1 a b 1k\nC1 b 0 1u\n.tran 1u 1m\n.end\n")
        system = System(net)
        state = {}
        a, b, _ = system.build("tran", dt=1e-6, state=state, t=1e-6)
        hist = state["C1"]
        self.assertAlmostEqual(hist["_g"], 2.0)      # 2C/dt, trap
        self.assertAlmostEqual(hist["_ieq"], 0.0)    # zero history


if __name__ == "__main__":
    unittest.main()
