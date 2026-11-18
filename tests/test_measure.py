import math
import unittest

from nodal import measure


class TestTranMeasures(unittest.TestCase):
    def setUp(self):
        # ideal RC step: tau = 1 ms, final 5 V, run to 8 tau
        self.times = [i * 1e-5 for i in range(801)]
        self.values = [5.0 * (1 - math.exp(-t / 1e-3)) for t in self.times]

    def test_final_value(self):
        self.assertAlmostEqual(measure.final_value(self.times, self.values),
                               5.0, delta=0.01)

    def test_rise_time(self):
        tr = measure.rise_time(self.times, self.values)
        self.assertLess(abs(tr - 2.197e-3) / 2.197e-3, 0.02)

    def test_overshoot_zero_for_monotonic(self):
        self.assertLess(measure.overshoot(self.times, self.values), 0.5)

    def test_overshoot_positive(self):
        times = [i * 1e-3 for i in range(101)]
        values = [1.0 + 0.3 * math.exp(-t / 0.02) *
                  math.sin(2 * math.pi * 20 * t) for t in times]
        values[0] = 0.0
        self.assertGreater(measure.overshoot(times, values), 5.0)

    def test_settling(self):
        ts = measure.settling_time(self.times, self.values, band=0.02)
        # 2% settling ~ 3.9 tau
        self.assertLess(abs(ts - 3.9e-3) / 3.9e-3, 0.1)

    def test_ripple(self):
        values = [4.0 + 0.1 * math.sin(2 * math.pi * i / 50)
                  for i in range(200)]
        self.assertAlmostEqual(measure.ripple(values), 0.2, places=2)

    def test_mean_rms(self):
        self.assertAlmostEqual(measure.mean([1, 2, 3]), 2.0)
        self.assertAlmostEqual(measure.rms([3, 4]), math.sqrt(12.5))

    def test_frequency(self):
        times = [i * 1e-5 for i in range(1000)]
        values = [math.sin(2 * math.pi * 1000 * t) for t in times]
        f = measure.frequency(times, values)
        self.assertLess(abs(f - 1000) / 1000, 0.01)

    def test_frequency_dc_none(self):
        self.assertIsNone(measure.frequency([0, 1, 2], [1, 1, 1]))

    def test_rise_time_flat_none(self):
        self.assertIsNone(measure.rise_time([0, 1], [2, 2]))


class TestAcMeasures(unittest.TestCase):
    def setUp(self):
        self.freqs = [10 ** (1 + i * 0.05) for i in range(101)]
        fc = 1e3
        self.db = [-10 * math.log10(1 + (f / fc) ** 2) for f in self.freqs]
        self.phase = [-math.degrees(math.atan(f / fc)) for f in self.freqs]

    def test_bandwidth(self):
        bw = measure.bandwidth(self.freqs, self.db)
        self.assertLess(abs(bw - 1e3) / 1e3, 0.15)

    def test_bandwidth_beyond(self):
        flat = [0.0] * len(self.freqs)
        self.assertIsNone(measure.bandwidth(self.freqs, flat))

    def test_peak_gain(self):
        pk = measure.peak_gain(self.freqs, self.db)
        self.assertAlmostEqual(pk["db"], 0.0, places=2)

    def test_phase_at(self):
        p = measure.phase_at(self.freqs, self.phase, 1e3)
        self.assertAlmostEqual(p, -45.0, delta=3.0)


if __name__ == "__main__":
    unittest.main()
