"""Waveform measurements: the numbers an engineer reads off a plot.

All routines take plain Python lists so they work on CLI output, tests
and the web workbench alike.
"""

import math


def final_value(times, values, tail=0.1):
    """Mean of the last `tail` fraction of the record."""
    n = len(values)
    k = max(1, int(n * tail))
    return sum(values[-k:]) / k


def rise_time(times, values, lo=0.1, hi=0.9):
    """10%-90% rise time of a monotonic-ish step response."""
    start = values[0]
    end = final_value(times, values)
    span = end - start
    if abs(span) < 1e-15:
        return None
    t_lo = t_hi = None
    for t, v in zip(times, values):
        frac = (v - start) / span
        if t_lo is None and frac >= lo:
            t_lo = t
        if t_hi is None and frac >= hi:
            t_hi = t
            break
    if t_lo is None or t_hi is None:
        return None
    return t_hi - t_lo


def overshoot(times, values):
    """Percent overshoot relative to the final value."""
    end = final_value(times, values)
    start = values[0]
    span = end - start
    if abs(span) < 1e-15:
        return 0.0
    peak = max(values) if span > 0 else min(values)
    return max(0.0, (peak - end) / span * 100.0)


def settling_time(times, values, band=0.02):
    """Last time the trace leaves a +/-band window around the final value."""
    end = final_value(times, values)
    tol = max(abs(end) * band, 1e-12)
    last_out = 0.0
    for t, v in zip(times, values):
        if abs(v - end) > tol:
            last_out = t
    return last_out


def ripple(values, tail=0.25):
    """Peak-to-peak ripple over the last `tail` fraction."""
    k = max(2, int(len(values) * tail))
    window = values[-k:]
    return max(window) - min(window)


def mean(values):
    return sum(values) / len(values) if values else 0.0


def rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def frequency(times, values):
    """Fundamental frequency estimate from upward mid-level crossings."""
    lo, hi = min(values), max(values)
    if hi - lo < 1e-15:
        return None
    mid = (lo + hi) / 2.0
    crossings = []
    for i in range(1, len(values)):
        if values[i - 1] < mid <= values[i]:
            t0, t1 = times[i - 1], times[i]
            v0, v1 = values[i - 1], values[i]
            frac = (mid - v0) / (v1 - v0) if v1 != v0 else 0.0
            crossings.append(t0 + frac * (t1 - t0))
    if len(crossings) < 2:
        return None
    periods = [b - a for a, b in zip(crossings, crossings[1:])]
    return 1.0 / (sum(periods) / len(periods))


def bandwidth(freqs, db, ref_db=None):
    """-3 dB bandwidth relative to the low-frequency (or peak) gain."""
    if ref_db is None:
        ref_db = db[0]
    for f, g in zip(freqs, db):
        if g <= ref_db - 3.0:
            return f
    return None


def peak_gain(freqs, db):
    idx = max(range(len(db)), key=lambda i: db[i])
    return {"freq": freqs[idx], "db": db[idx]}


def phase_at(freqs, phases, target):
    """Phase (deg) at the first frequency >= target, linearly interpolated."""
    for i in range(1, len(freqs)):
        if freqs[i] >= target:
            f0, f1 = freqs[i - 1], freqs[i]
            p0, p1 = phases[i - 1], phases[i]
            w = (target - f0) / (f1 - f0) if f1 != f0 else 0.0
            return p0 + w * (p1 - p0)
    return phases[-1] if phases else None


def summarise_tran(times, traces):
    out = {}
    for label, values in traces.items():
        out[label] = {
            "min": min(values), "max": max(values),
            "mean": mean(values), "rms": rms(values),
            "final": final_value(times, values),
            "rise_time": rise_time(times, values),
            "overshoot_pct": overshoot(times, values),
            "ripple_pp": ripple(values),
            "freq": frequency(times, values),
        }
    return out


def summarise_ac(freqs, traces):
    out = {}
    for label, data in traces.items():
        out[label] = {
            "dc_gain_db": data["db"][0],
            "bandwidth": bandwidth(freqs, data["db"]),
            "peak": peak_gain(freqs, data["db"]),
        }
    return out
