"""Local HTTP server: JSON API + the static workbench.

Binds 127.0.0.1 only.  No auth, no TLS - a local teaching tool.
"""

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, analysis, measure, visual
from .netlist import NetlistError, parse, parse_value


def _num(value):
    """Accept plain numbers and engineering-suffix strings (10u, 1meg)."""
    return parse_value(str(value))

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_BODY = 256 * 1024
MAX_TRAN_POINTS = 8000
MAX_AC_POINTS = 2000

_CONTENT_TYPES = {".html": "text/html; charset=utf-8",
                  ".css": "text/css; charset=utf-8",
                  ".js": "application/javascript; charset=utf-8",
                  ".svg": "image/svg+xml"}


def _net(payload):
    text = str(payload.get("netlist", ""))
    if not text.strip():
        raise ValueError("netlist is empty")
    return parse(text)


def _api_info(_payload):
    return {
        "name": "Nodal",
        "version": __version__,
        "elements": ["R", "C", "L", "V", "I", "D", "E", "G", "F", "H"],
        "analyses": ["op", "dc", "tran (trap/be)", "ac (dec/oct/lin)"],
        "examples": visual.EXAMPLES,
        "warning": ("Educational simulator: idealised models, no temperature, "
                    "no BSIM, not sign-off quality."),
    }


def _api_parse(payload):
    net = _net(payload)
    return {"title": net.title,
            "elements": net.elements,
            "nodes": net.node_names(),
            "models": net.models,
            "analyses": net.analyses}


def _api_op(payload):
    net = _net(payload)
    report = visual.newton_report(net)
    return report


def _api_tran(payload):
    net = _net(payload)
    spec = next((a for a in net.analyses if a["kind"] == "tran"), None)
    tstep = _num(payload.get("tstep") or (spec and spec["tstep"]) or 1e-5)
    tstop = _num(payload.get("tstop") or (spec and spec["tstop"]) or 1e-3)
    method = payload.get("method", "trap")
    if method not in ("trap", "be"):
        raise ValueError("method must be trap or be")
    if tstop / tstep > MAX_TRAN_POINTS:
        raise ValueError("too many transient points (limit %d)"
                         % MAX_TRAN_POINTS)
    tr = analysis.transient(net, tstep, tstop, method=method,
                            uic=bool(payload.get("uic")))
    obj = analysis._serialise_tran(tr, net.outputs or None)
    obj["summary"] = measure.summarise_tran(obj["times"], obj["traces"])
    small = visual.downsample(obj["times"], obj["traces"])
    obj["plot"] = small
    return obj


def _api_ac(payload):
    net = _net(payload)
    spec = next((a for a in net.analyses if a["kind"] == "ac"), None)
    mode = payload.get("mode") or (spec and spec["mode"]) or "dec"
    n = int(payload.get("n") or (spec and spec["n"]) or 20)
    fstart = _num(payload.get("fstart") or (spec and spec["fstart"]) or 1)
    fstop = _num(payload.get("fstop") or (spec and spec["fstop"]) or 1e6)
    if mode not in ("dec", "oct", "lin"):
        raise ValueError("mode must be dec/oct/lin")
    ac = analysis.ac_sweep(net, mode, min(n, 200), fstart, fstop)
    if len(ac["freqs"]) > MAX_AC_POINTS:
        raise ValueError("too many AC points")
    obj = analysis._serialise_ac(ac, net.outputs or None)
    obj["summary"] = measure.summarise_ac(obj["freqs"], obj["traces"])
    return obj


def _api_dc(payload):
    net = _net(payload)
    spec = next((a for a in net.analyses if a["kind"] == "dc"), None)
    source = payload.get("source") or (spec and spec["source"])
    if not source:
        raise ValueError("dc sweep needs a source")
    start = _num(payload.get("start") if payload.get("start") is not None
                  else (spec and spec["start"]) or 0)
    stop = _num(payload.get("stop") if payload.get("stop") is not None
                 else (spec and spec["stop"]) or 5)
    step = _num(payload.get("step") if payload.get("step") is not None
                 else (spec and spec["step"]) or 0.1)
    if step == 0 or abs((stop - start) / step) > 2000:
        raise ValueError("invalid dc sweep range/step")
    dc = analysis.dc_sweep(net, source, start, stop, step)
    return analysis._serialise_dc(dc, net.outputs or None)


def _api_matrix(payload):
    net = _net(payload)
    mode = payload.get("mode", "op")
    if mode not in ("op", "ac"):
        raise ValueError("mode must be op or ac")
    return visual.matrix_view(net, mode)


def _api_bench(payload):
    stages = max(2, min(int(payload.get("stages", 16)), 48))
    points = max(50, min(int(payload.get("points", 200)), 1000))
    ac_points = max(10, min(int(payload.get("ac_points", 40)), 200))
    return visual.bench(stages, points, ac_points)


_ROUTES = {
    "/api/parse": _api_parse,
    "/api/op": _api_op,
    "/api/tran": _api_tran,
    "/api/ac": _api_ac,
    "/api/dc": _api_dc,
    "/api/matrix": _api_matrix,
    "/api/bench": _api_bench,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Nodal/1.0"

    def log_message(self, fmt, *args):
        if os.environ.get("NODAL_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200):
        self._send(status, json.dumps(obj, ensure_ascii=False,
                                      default=str).encode("utf-8"))

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/info":
            self._json(_api_info({}))
            return
        if path == "/":
            path = "/index.html"
        name = os.path.basename(path)
        candidate = os.path.join(WEB_DIR, name)
        if not os.path.isfile(candidate):
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        with open(candidate, "rb") as fh:
            body = fh.read()
        ext = os.path.splitext(name)[1]
        self._send(200, body,
                   _CONTENT_TYPES.get(ext, "application/octet-stream"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        route = _ROUTES.get(path)
        if route is None:
            self._json({"error": "unknown endpoint"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY:
                raise ValueError("request body too large")
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
            self._json(route(payload))
        except (NetlistError, analysis.AnalysisError, ValueError,
                TypeError, KeyError) as exc:
            self._json({"error": str(exc)}, 400)


def build_server(port=8863, host="127.0.0.1"):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def run(port=8863, open_browser=True):
    httpd = build_server(port)
    url = "http://127.0.0.1:%d/" % port
    print("Nodal workbench: %s" % url)
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
