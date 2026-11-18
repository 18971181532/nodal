import contextlib
import io
import json
import os
import tempfile
import unittest

from nodal import visual
from nodal.cli import main


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class CliTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = {}
        for name, text in visual.EXAMPLES.items():
            path = os.path.join(cls.tmp.name, name + ".cir")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            cls.files[name] = path

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_parse_json(self):
        code, out, _ = run_cli(["parse", self.files["divider"], "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["elements"]), 3)

    def test_op(self):
        code, out, _ = run_cli(["op", self.files["divider"], "--json"])
        self.assertEqual(code, 0)
        self.assertAlmostEqual(json.loads(out)["voltages"]["mid"], 6.0)

    def test_op_text(self):
        code, out, _ = run_cli(["op", self.files["divider"]])
        self.assertEqual(code, 0)
        self.assertIn("v(mid)", out)

    def test_tran(self):
        code, out, _ = run_cli(["tran", self.files["rc"], "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertGreater(len(data["times"]), 100)
        self.assertIn("summary", data)

    def test_tran_be_override(self):
        code, out, _ = run_cli(["tran", self.files["rc"], "--method", "be",
                                "--step", "20u", "--stop", "2m", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["method"], "be")

    def test_ac(self):
        code, out, _ = run_cli(["ac", self.files["rlc"], "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("v(out)", data["traces"])
        self.assertIn("bandwidth", data["summary"]["v(out)"])

    def test_dc_flags(self):
        code, out, _ = run_cli(["dc", self.files["divider"], "--source", "V1",
                                "--start", "0", "--stop", "10",
                                "--step", "2", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["sweep"], [0, 2, 4, 6, 8, 10])
        self.assertAlmostEqual(data["traces"]["v(mid)"][-1], 6.0)

    def test_run(self):
        code, out, _ = run_cli(["run", self.files["rc"], "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["results"][0]["analysis"], "tran")

    def test_matrix(self):
        code, out, _ = run_cli(["matrix", self.files["divider"], "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["size"], 3)

    def test_matrix_text(self):
        code, out, _ = run_cli(["matrix", self.files["divider"]])
        self.assertEqual(code, 0)
        self.assertIn("MNA matrix", out)

    def test_newton(self):
        code, out, _ = run_cli(["newton", self.files["divider"], "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["iterations"], 1)

    def test_bench(self):
        code, out, _ = run_cli(["bench", "--stages", "6", "--points", "60",
                                "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["matrix_size"], 8)

    def test_bad_file_exit_2(self):
        code, _, err = run_cli(["op", "no_such_file.cir"])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_bad_netlist_exit_2(self):
        path = os.path.join(self.tmp.name, "bad.cir")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("bad\nR1 a b\n.end\n")
        code, _, err = run_cli(["op", path])
        self.assertEqual(code, 2)
        self.assertIn("line 2", err)


if __name__ == "__main__":
    unittest.main()
