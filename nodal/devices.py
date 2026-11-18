"""Device physics: the Shockley diode and source waveforms.

The diode uses the classic SPICE junction-limiting scheme so that Newton
iterations cannot overflow ``exp`` on the first guess.
"""

import math

# thermal voltage at 300 K (SPICE default TNOM = 27 C -> 300.15 K, close enough)
VT = 0.025865


def diode_current(vd, model):
    """Shockley equation, guarded against overflow."""
    nvt = model["N"] * VT
    arg = vd / nvt
    if arg > 40.0:
        # linear continuation keeps Newton well-behaved far outside the knee
        e40 = math.exp(40.0)
        return model["IS"] * (e40 * (1.0 + arg - 40.0) - 1.0)
    return model["IS"] * (math.exp(arg) - 1.0)


def diode_conductance(vd, model):
    nvt = model["N"] * VT
    arg = vd / nvt
    if arg > 40.0:
        return model["IS"] * math.exp(40.0) / nvt
    return model["IS"] * math.exp(arg) / nvt


def diode_limit(vnew, vold, model):
    """SPICE pn-junction limiting: clamp the per-iteration voltage step."""
    nvt = model["N"] * VT
    vcrit = nvt * math.log(nvt / (math.sqrt(2.0) * model["IS"]))
    if vnew > vcrit and abs(vnew - vold) > 2.0 * nvt:
        if vold > 0.0:
            arg = 1.0 + (vnew - vold) / nvt
            if arg > 0.0:
                vnew = vold + nvt * math.log(arg)
            else:
                vnew = vcrit
        else:
            vnew = nvt * math.log(max(vnew / nvt, 1e-3))
    elif vnew < 0.0:
        # reverse bias: limit the step to -5 V per iteration
        vnew = max(vnew, vold - 5.0) if vold < 0.0 else max(vnew, -5.0)
    return vnew


def source_value(spec, t):
    """Instantaneous value of an independent source at time t (tran)."""
    wave = spec.get("wave")
    if wave is None or t is None:
        return spec["dc"]
    if wave["kind"] == "sin":
        if t <= wave["td"]:
            return wave["off"]
        dt = t - wave["td"]
        damp = math.exp(-wave["theta"] * dt) if wave["theta"] else 1.0
        return wave["off"] + wave["amp"] * damp * math.sin(
            2.0 * math.pi * wave["freq"] * dt)
    # pulse
    v1, v2 = wave["v1"], wave["v2"]
    td, tr, tf, pw, per = (wave["td"], wave["tr"], wave["tf"],
                           wave["pw"], wave["per"])
    if t < td:
        return v1
    tt = t - td
    if per > 0:
        tt %= per
    if tr > 0 and tt < tr:
        return v1 + (v2 - v1) * tt / tr
    tt -= tr
    if tt < pw:
        return v2
    tt -= pw
    if tf > 0 and tt < tf:
        return v2 + (v1 - v2) * tt / tf
    return v1
