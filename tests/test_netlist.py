import unittest

from nodal.netlist import NetlistError, parse, parse_value


class TestValues(unittest.TestCase):
    def assertValue(self, token, expect):
        got = parse_value(token)
        self.assertAlmostEqual(got / expect, 1.0, places=12)

    def test_suffixes(self):
        self.assertValue("4.7k", 4700.0)
        self.assertValue("1meg", 1e6)
        self.assertValue("10m", 0.01)
        self.assertValue("2u", 2e-6)
        self.assertValue("100n", 1e-7)
        self.assertValue("3p", 3e-12)
        self.assertValue("1e-3", 1e-3)
        self.assertValue("2.2K", 2200.0)
        self.assertValue("10V", 10.0)   # trailing unit ignored

    def test_bad_value(self):
        with self.assertRaises(NetlistError):
            parse_value("abc")


class TestParse(unittest.TestCase):
    BASIC = """test circuit
V1 in 0 DC 5
R1 in out 1k
R2 out 0 2k
.op
.end
"""

    def test_basic(self):
        net = parse(self.BASIC)
        self.assertEqual(net.title, "test circuit")
        self.assertEqual(len(net.elements), 3)
        self.assertEqual(net.node_names(), ["in", "out"])
        self.assertEqual(net.analyses, [{"kind": "op"}])

    def test_comments_and_continuation(self):
        net = parse("""title
* full comment
V1 in 0 DC 5 $ inline
R1 in out
+ 1k
.end
""")
        self.assertEqual(net.elements[1]["value"], 1000.0)
        self.assertEqual(net.elements[0]["dc"], 5.0)

    def test_sin_pulse(self):
        net = parse("""t
V1 a 0 SIN(1 2 1k)
V2 b 0 PULSE(0 5 1u 10n 10n 100u 200u)
I1 0 c DC 2u AC 1
.op
.end
""")
        v1, v2, i1 = net.elements
        self.assertEqual(v1["wave"]["kind"], "sin")
        self.assertEqual(v1["wave"]["freq"], 1000.0)
        self.assertAlmostEqual(v2["wave"]["per"] / 200e-6, 1.0, places=12)
        self.assertEqual(i1["ac"], 1.0)

    def test_model_and_diode(self):
        net = parse("""t
D1 a k DM
R1 k 0 1k
.model DM D(IS=1e-15 N=1.2)
.op
.end
""")
        self.assertEqual(net.models["DM"]["IS"], 1e-15)
        self.assertEqual(net.models["DM"]["N"], 1.2)

    def test_controlled_sources(self):
        net = parse("""t
V1 in 0 1
E1 out 0 in 0 100
G1 o2 0 in 0 1m
Vsense s 0 0
F1 o3 0 Vsense 10
H1 o4 0 Vsense 1k
R1 out 0 1k
.op
.end
""")
        kinds = [el["kind"] for el in net.elements]
        self.assertEqual(kinds.count("E"), 1)
        self.assertEqual(net.elements[-3]["control"], "Vsense")

    def test_analyses(self):
        net = parse("""t
V1 in 0 1 AC 1
R1 in out 1k
C1 out 0 1u
.tran 1u 1m 0 5u uic
.ac dec 20 1 1meg
.dc V1 0 5 0.5
.print tran v(out) i(V1)
.end
""")
        tran, ac, dc = net.analyses
        self.assertTrue(tran["uic"])
        self.assertAlmostEqual(tran["tmax"] / 5e-6, 1.0, places=12)
        self.assertEqual(ac["mode"], "dec")
        self.assertEqual(dc["step"], 0.5)
        self.assertEqual(net.outputs, [("v", "out"), ("i", "v1")])

    def test_errors(self):
        cases = [
            "t\nR1 a b\n.end\n",                    # missing value
            "t\nX1 a b 1\n.end\n",                  # unsupported element
            "t\nR1 a b 1k\nR1 c d 2k\n.end\n",      # duplicate name
            "t\nD1 a k NOPE\n.end\n",               # unknown model
            "t\nR1 a b 1k\n.end\n",                 # no ground
            "t\nF1 a 0 R1 5\nR1 a 0 1k\n.end\n",    # F controlled by R
            "t\n.tran 0 1m\nR1 a 0 1k\n.end\n",     # zero step
        ]
        for text in cases:
            with self.assertRaises(NetlistError, msg=text):
                parse(text)

    def test_error_line_number(self):
        try:
            parse("t\nR1 a 0 1k\nR2 a b xyz\n.end\n")
            self.fail("should raise")
        except NetlistError as exc:
            self.assertEqual(exc.line, 3)


if __name__ == "__main__":
    unittest.main()
