import unittest

from nodal import visual
from nodal.netlist import parse


class TestMatrixView(unittest.TestCase):
    def test_shape_and_labels(self):
        net = parse(visual.EXAMPLES["divider"])
        view = visual.matrix_view(net)
        self.assertEqual(view["size"], 3)          # in, mid + i(V1)
        self.assertEqual(len(view["values"]), 3)
        self.assertEqual(len(view["rhs"]), 3)
        self.assertEqual(view["labels"][0], "v(in)")
        self.assertGreater(view["nonzeros"], 0)
        self.assertLessEqual(view["density"], 1.0)

    def test_cells_normalised(self):
        net = parse(visual.EXAMPLES["divider"])
        view = visual.matrix_view(net)
        for row in view["cells"]:
            for c in row:
                self.assertGreaterEqual(c, 0.0)
                self.assertLessEqual(c, 1.0001)

    def test_ac_mode_magnitudes(self):
        net = parse(visual.EXAMPLES["rlc"])
        view = visual.matrix_view(net, "ac")
        for row in view["values"]:
            for v in row:
                self.assertIsInstance(v, float)   # magnitudes, not complex


class TestNewtonReport(unittest.TestCase):
    def test_linear_one_iteration(self):
        report = visual.newton_report(parse(visual.EXAMPLES["divider"]))
        self.assertEqual(report["iterations"], 1)
        self.assertAlmostEqual(report["voltages"]["mid"], 6.0)

    def test_diode_multi_iteration(self):
        net = parse("""t
V1 in 0 5
R1 in out 1k
D1 out 0 DM
.model DM D(IS=1e-14 N=1)
.op
.end
""")
        report = visual.newton_report(net)
        self.assertGreater(report["iterations"], 1)
        self.assertEqual(len(report["trace"]), report["iterations"])
        # last recorded step should be small
        self.assertLess(report["trace"][-1]["dv"], 1e-3)


class TestDownsample(unittest.TestCase):
    def test_small_unchanged(self):
        out = visual.downsample([0, 1, 2], {"a": [1, 2, 3]}, limit=10)
        self.assertEqual(out["times"], [0, 1, 2])

    def test_large_decimated_with_endpoints(self):
        times = list(range(5000))
        traces = {"a": times}
        out = visual.downsample(times, traces, limit=100)
        self.assertLessEqual(len(out["times"]), 102)
        self.assertEqual(out["times"][0], 0)
        self.assertEqual(out["times"][-1], 4999)


class TestBench(unittest.TestCase):
    def test_bench_runs(self):
        result = visual.bench(stages=6, tran_points=60, ac_points=20)
        self.assertEqual(result["matrix_size"], 8)   # 7 nodes + i(V1)
        self.assertGreater(result["op_ms"], 0)
        self.assertGreaterEqual(result["tran_points"], 60)
        self.assertGreaterEqual(result["ac_points"], 5)


class TestExamples(unittest.TestCase):
    def test_all_examples_parse_and_run(self):
        from nodal import analysis
        for name, text in visual.EXAMPLES.items():
            net = parse(text)
            results = analysis.run_netlist(net)
            self.assertTrue(results, name)


if __name__ == "__main__":
    unittest.main()
