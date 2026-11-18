"""SPICE-subset netlist parser.

Supported elements
    R C L            passive, value with engineering suffix
    V I              independent sources: DC value | SIN(...) | PULSE(...)
                     optional ``AC mag [phase]`` for small-signal analysis
    D                diode, references a ``.model NAME D(IS=..., N=...)``
    E G F H          VCVS / VCCS / CCCS / CCVS (F and H are controlled by
                     the current through a named voltage source)

Supported commands
    .op  .tran  .ac  .dc  .model  .print/.plot  .options  .end

Line continuation with a leading ``+``, ``*`` full-line comments and
inline ``$``/``;`` comments follow SPICE conventions.
"""

import re

SUFFIXES = {
    "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
    "m": 1e-3, "mil": 25.4e-6,
    "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15,
}

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_VALUE_RE = re.compile(r"^(" + _NUM + r")\s*([a-zA-Z]*)")


class NetlistError(ValueError):
    def __init__(self, message, line=None):
        self.line = line
        super().__init__(("line %d: %s" % (line, message)) if line else message)


def parse_value(token, line=None):
    """'4.7k' -> 4700.0 ; '10' -> 10.0 ; trailing unit letters ignored."""
    match = _VALUE_RE.match(token.strip())
    if not match:
        raise NetlistError("cannot parse value %r" % token, line)
    number, suffix = match.groups()
    suffix = suffix.lower()
    scale = 1.0
    if suffix:
        for key in sorted(SUFFIXES, key=len, reverse=True):
            if suffix.startswith(key):
                scale = SUFFIXES[key]
                break
        # unknown trailing letters are unit labels (V, A, HZ...) - SPICE
        # convention: ignore them
    return float(number) * scale


def _tokens(text):
    # split but keep parenthesised groups together
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch.isspace() and depth == 0:
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _parse_waveform(token, line):
    """SIN(off amp freq [td [theta]]) or PULSE(v1 v2 [td [tr [tf [pw [per]]]])."""
    match = re.match(r"^(sin|pulse|exp)\((.*)\)$", token, re.IGNORECASE)
    if not match:
        raise NetlistError("unsupported waveform %r" % token, line)
    kind = match.group(1).lower()
    args = [parse_value(a, line) for a in match.group(2).replace(",", " ").split()]
    if kind == "sin":
        if len(args) < 3:
            raise NetlistError("SIN needs offset amplitude frequency", line)
        off, amp, freq = args[:3]
        td = args[3] if len(args) > 3 else 0.0
        theta = args[4] if len(args) > 4 else 0.0
        return {"kind": "sin", "off": off, "amp": amp, "freq": freq,
                "td": td, "theta": theta}
    if kind == "pulse":
        if len(args) < 2:
            raise NetlistError("PULSE needs v1 v2", line)
        v1, v2 = args[:2]
        td, tr, tf, pw, per = (args + [0.0] * 7)[2:7]
        return {"kind": "pulse", "v1": v1, "v2": v2, "td": td,
                "tr": tr, "tf": tf, "pw": pw, "per": per}
    raise NetlistError("EXP waveform is not implemented", line)


def _source_spec(tokens, line):
    """Parse the value part of a V/I line into dc / wave / ac fields."""
    spec = {"dc": 0.0, "wave": None, "ac": 0.0, "ac_phase": 0.0}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        upper = tok.upper()
        if upper == "DC":
            i += 1
            spec["dc"] = parse_value(tokens[i], line)
        elif upper == "AC":
            i += 1
            spec["ac"] = parse_value(tokens[i], line)
            if i + 1 < len(tokens) and not tokens[i + 1].upper().startswith(
                    ("DC", "SIN", "PULSE")):
                try:
                    spec["ac_phase"] = parse_value(tokens[i + 1], line)
                    i += 1
                except NetlistError:
                    pass
        elif upper.startswith(("SIN(", "PULSE(")):
            spec["wave"] = _parse_waveform(tok, line)
        else:
            spec["dc"] = parse_value(tok, line)
        i += 1
    return spec


class Netlist:
    def __init__(self, title=""):
        self.title = title
        self.elements = []      # dicts: kind, name, nodes, ...
        self.models = {}        # name -> {"type": "D", "IS":..., "N":...}
        self.analyses = []      # dicts: kind + parameters
        self.outputs = []       # [("v", node) | ("i", source)]
        self.options = {"reltol": 1e-3, "abstol": 1e-12, "voltol": 1e-6,
                        "maxiter": 100}

    def nodes(self):
        seen = []
        for el in self.elements:
            for node in el["nodes"]:
                if node not in seen:
                    seen.append(node)
        return seen

    def node_names(self):
        return [n for n in self.nodes() if n != "0"]


def _element(fields, line):
    name = fields[0]
    kind = name[0].upper()
    lower = [f.lower() if f != "0" else "0" for f in fields]
    # node names are case-insensitive in SPICE; normalise to lower case
    if kind in ("R", "C", "L"):
        if len(fields) < 4:
            raise NetlistError("%s needs two nodes and a value" % kind, line)
        return {"kind": kind, "name": name, "nodes": [lower[1], lower[2]],
                "value": parse_value(fields[3], line)}
    if kind in ("V", "I"):
        if len(fields) < 4:
            raise NetlistError("%s needs two nodes and a value" % kind, line)
        el = {"kind": kind, "name": name, "nodes": [lower[1], lower[2]]}
        el.update(_source_spec(fields[3:], line))
        return el
    if kind == "D":
        if len(fields) < 4:
            raise NetlistError("D needs anode cathode model", line)
        return {"kind": "D", "name": name, "nodes": [lower[1], lower[2]],
                "model": fields[3]}
    if kind in ("E", "G"):
        if len(fields) < 6:
            raise NetlistError("%s needs 4 nodes and a gain" % kind, line)
        return {"kind": kind, "name": name,
                "nodes": [lower[1], lower[2], lower[3], lower[4]],
                "gain": parse_value(fields[5], line)}
    if kind in ("F", "H"):
        if len(fields) < 5:
            raise NetlistError("%s needs 2 nodes, a controlling V source "
                               "and a gain" % kind, line)
        return {"kind": kind, "name": name, "nodes": [lower[1], lower[2]],
                "control": fields[3], "gain": parse_value(fields[4], line)}
    raise NetlistError("unsupported element %r" % name, line)


def _model(fields, line):
    if len(fields) < 3:
        raise NetlistError(".model needs a name and a type", line)
    name = fields[1]
    body = " ".join(fields[2:])
    match = re.match(r"^([A-Za-z]+)\s*(?:\((.*)\))?$", body, re.DOTALL)
    if not match:
        raise NetlistError("cannot parse .model body", line)
    mtype = match.group(1).upper()
    if mtype != "D":
        raise NetlistError("only diode models (D) are supported", line)
    params = {"IS": 1e-14, "N": 1.0}
    body = match.group(2) or ""
    for match in re.finditer(r"([A-Za-z]+)\s*=\s*(" + _NUM + r"[a-zA-Z]*)", body):
        key = match.group(1).upper()
        if key not in params:
            raise NetlistError("unknown diode parameter %r (supported: IS, N)"
                               % key, line)
        params[key] = parse_value(match.group(2), line)
    if params["IS"] <= 0 or params["N"] <= 0:
        raise NetlistError("IS and N must be positive", line)
    return name, {"type": "D", **params}


def _analysis(fields, line):
    cmd = fields[0].lower()
    if cmd == ".op":
        return {"kind": "op"}
    if cmd == ".tran":
        if len(fields) < 3:
            raise NetlistError(".tran needs tstep tstop", line)
        spec = {"kind": "tran",
                "tstep": parse_value(fields[1], line),
                "tstop": parse_value(fields[2], line)}
        if len(fields) > 3:
            spec["tstart"] = parse_value(fields[3], line)
        if len(fields) > 4 and fields[4].upper() != "UIC":
            spec["tmax"] = parse_value(fields[4], line)
        spec["uic"] = any(f.upper() == "UIC" for f in fields[3:])
        if spec["tstep"] <= 0 or spec["tstop"] <= 0:
            raise NetlistError(".tran times must be positive", line)
        return spec
    if cmd == ".ac":
        if len(fields) < 5:
            raise NetlistError(".ac needs mode n fstart fstop", line)
        mode = fields[1].lower()
        if mode not in ("dec", "oct", "lin"):
            raise NetlistError(".ac mode must be dec/oct/lin", line)
        n = int(parse_value(fields[2], line))
        fstart = parse_value(fields[3], line)
        fstop = parse_value(fields[4], line)
        if n < 1 or fstart <= 0 or fstop < fstart:
            raise NetlistError("invalid .ac sweep parameters", line)
        return {"kind": "ac", "mode": mode, "n": n,
                "fstart": fstart, "fstop": fstop}
    if cmd == ".dc":
        if len(fields) < 5:
            raise NetlistError(".dc needs source start stop step", line)
        step = parse_value(fields[4], line)
        if step == 0:
            raise NetlistError(".dc step must be non-zero", line)
        return {"kind": "dc", "source": fields[1],
                "start": parse_value(fields[2], line),
                "stop": parse_value(fields[3], line), "step": step}
    raise NetlistError("unsupported analysis %r" % cmd, line)


def parse(text):
    """Parse netlist text into a :class:`Netlist`.  Raises NetlistError."""
    raw_lines = text.splitlines()
    logical = []          # (line_number, content)
    for idx, raw in enumerate(raw_lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("*"):
            continue
        for marker in ("$", ";"):
            if marker in stripped:
                stripped = stripped.split(marker, 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith("+"):
            if not logical:
                raise NetlistError("continuation without a previous line", idx)
            prev_no, prev = logical[-1]
            logical[-1] = (prev_no, prev + " " + stripped[1:].strip())
        else:
            logical.append((idx, stripped))

    net = Netlist()
    if logical:
        net.title = logical[0][1]
    ended = False
    for line_no, content in logical[1:] if logical else []:
        fields = _tokens(content)
        if not fields:
            continue
        head = fields[0].lower()
        if head == ".end":
            ended = True
            break
        if head == ".model":
            name, model = _model(fields, line_no)
            net.models[name] = model
        elif head in (".print", ".plot"):
            for tok in fields[2:]:
                match = re.match(r"^([vi])\((.+)\)$", tok, re.IGNORECASE)
                if not match:
                    raise NetlistError("output must be v(node) or i(Vname)",
                                       line_no)
                net.outputs.append((match.group(1).lower(),
                                    match.group(2).lower()))
        elif head == ".options":
            body = " ".join(fields[1:])
            for match in re.finditer(r"([A-Za-z]+)\s*=\s*(" + _NUM + r"[a-zA-Z]*)",
                                     body):
                key = match.group(1).lower()
                if key in net.options:
                    net.options[key] = parse_value(match.group(2), line_no)
        elif head.startswith("."):
            net.analyses.append(_analysis(fields, line_no))
        else:
            net.elements.append(_element(fields, line_no))

    names = [el["name"].lower() for el in net.elements]
    if len(names) != len(set(names)):
        raise NetlistError("duplicate element name")
    vnames = {el["name"].lower() for el in net.elements if el["kind"] == "V"}
    for el in net.elements:
        if el["kind"] == "D" and el["model"] not in net.models:
            raise NetlistError("diode %s references unknown model %r"
                               % (el["name"], el["model"]))
        if el["kind"] in ("F", "H") and el["control"].lower() not in vnames:
            raise NetlistError("%s must be controlled by a voltage source"
                               % el["name"])
    if not net.elements:
        raise NetlistError("netlist has no elements")
    if "0" not in net.nodes():
        raise NetlistError("circuit has no ground node (0)")
    net._ended = ended
    return net
