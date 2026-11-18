import json
import threading
import unittest
import urllib.error
import urllib.request

from nodal import visual
from nodal.server import build_server


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = build_server(port=0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def post(self, path, payload):
        req = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def get(self, path):
        with urllib.request.urlopen(self.url(path), timeout=10) as res:
            return res.status, res.read()

    def test_info(self):
        status, body = self.get("/api/info")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(data["name"], "Nodal")
        self.assertIn("rc", data["examples"])

    def test_index_and_assets(self):
        for path in ("/", "/style.css", "/app.js"):
            status, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertGreater(len(body), 100, path)

    def test_404(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.get("/nope.js")

    def test_parse(self):
        status, data = self.post("/api/parse",
                                 {"netlist": visual.EXAMPLES["divider"]})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["elements"]), 3)

    def test_op(self):
        status, data = self.post("/api/op",
                                 {"netlist": visual.EXAMPLES["divider"]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["voltages"]["mid"], 6.0)

    def test_tran(self):
        status, data = self.post("/api/tran", {
            "netlist": visual.EXAMPLES["rc"],
            "tstep": 1e-5, "tstop": 2e-3, "method": "trap"})
        self.assertEqual(status, 200)
        self.assertIn("plot", data)
        self.assertIn("summary", data)
        self.assertLessEqual(len(data["plot"]["times"]), 1200)

    def test_ac(self):
        status, data = self.post("/api/ac", {
            "netlist": visual.EXAMPLES["rlc"],
            "mode": "dec", "n": 20, "fstart": 100, "fstop": 1e6})
        self.assertEqual(status, 200)
        self.assertIn("db", data["traces"]["v(out)"])

    def test_dc(self):
        status, data = self.post("/api/dc", {
            "netlist": visual.EXAMPLES["divider"],
            "source": "V1", "start": 0, "stop": 10, "step": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["sweep"], [0, 5, 10])

    def test_matrix(self):
        status, data = self.post("/api/matrix",
                                 {"netlist": visual.EXAMPLES["divider"]})
        self.assertEqual(status, 200)
        self.assertEqual(data["size"], 3)

    def test_bench(self):
        status, data = self.post("/api/bench", {"stages": 4, "points": 50})
        self.assertEqual(status, 200)
        self.assertGreater(data["op_ms"], 0)

    def test_errors_400(self):
        cases = [
            ("/api/parse", {"netlist": ""}),
            ("/api/parse", {"netlist": "t\nR1 a b\n.end\n"}),
            ("/api/tran", {"netlist": visual.EXAMPLES["rc"],
                           "tstep": 1e-12, "tstop": 1}),
            ("/api/ac", {"netlist": visual.EXAMPLES["rlc"],
                         "mode": "bogus"}),
            ("/api/dc", {"netlist": visual.EXAMPLES["divider"]}),
            ("/api/matrix", {"netlist": visual.EXAMPLES["divider"],
                             "mode": "zzz"}),
        ]
        for path, payload in cases:
            status, data = self.post(path, payload)
            self.assertEqual(status, 400, (path, payload))
            self.assertIn("error", data)

    def test_unknown_endpoint(self):
        status, data = self.post("/api/nothing", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
