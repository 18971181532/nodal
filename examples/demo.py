"""Run every bundled example and print an engineering summary.

    python examples/demo.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nodal import analysis, measure, visual          # noqa: E402
from nodal.netlist import parse                      # noqa: E402


def main():
    for name, text in visual.EXAMPLES.items():
        net = parse(text)
        print("=" * 64)
        print("%s  --  %s" % (name, net.title))
        for res in analysis.run_netlist(net):
            kind = res["analysis"]
            if kind == "op":
                for node, v in res["voltages"].items():
                    print("  op   v(%s) = %.6g V" % (node, v))
            elif kind == "tran":
                summary = measure.summarise_tran(res["times"], res["traces"])
                print("  tran %d points (%s)" % (len(res["times"]),
                                                 res["method"]))
                for label, s in summary.items():
                    extra = ""
                    if s["rise_time"]:
                        extra += "  rise=%.4g s" % s["rise_time"]
                    if s["freq"]:
                        extra += "  f=%.4g Hz" % s["freq"]
                    print("    %-10s final=%.6g  ripple=%.4g%s" %
                          (label, s["final"], s["ripple_pp"], extra))
            elif kind == "ac":
                summary = measure.summarise_ac(res["freqs"], res["traces"])
                print("  ac   %d frequencies" % len(res["freqs"]))
                for label, s in summary.items():
                    bw = s["bandwidth"]
                    print("    %-10s gain=%.2f dB  peak=%.2f dB @ %.4g Hz"
                          "  -3dB BW=%s" %
                          (label, s["dc_gain_db"], s["peak"]["db"],
                           s["peak"]["freq"],
                           ("%.4g Hz" % bw) if bw else "beyond sweep"))
    print("=" * 64)
    print("bench:", visual.bench(16, 200, 40))


if __name__ == "__main__":
    main()
