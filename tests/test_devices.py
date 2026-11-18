import math
import unittest

from nodal import devices


class TestDiode(unittest.TestCase):
    MODEL = {"IS": 1e-14, "N": 1.0}

    def test_shockley_at_06(self):
        i = devices.diode_current(0.6, self.MODEL)
        expect = 1e-14 * (math.exp(0.6 / devices.VT) - 1)
        self.assertAlmostEqual(i / expect, 1.0, places=6)

    def test_reverse_saturation(self):
        i = devices.diode_current(-1.0, self.MODEL)
        self.assertAlmostEqual(i, -1e-14, places=18)

    def test_zero(self):
        self.assertEqual(devices.diode_current(0.0, self.MODEL), 0.0)

    def test_no_overflow_at_10v(self):
        i = devices.diode_current(10.0, self.MODEL)
        g = devices.diode_conductance(10.0, self.MODEL)
        self.assertTrue(math.isfinite(i))
        self.assertTrue(math.isfinite(g))
        self.assertGreater(g, 0)

    def test_conductance_matches_derivative(self):
        v = 0.55
        h = 1e-7
        numeric = (devices.diode_current(v + h, self.MODEL) -
                   devices.diode_current(v - h, self.MODEL)) / (2 * h)
        analytic = devices.diode_conductance(v, self.MODEL)
        self.assertAlmostEqual(numeric / analytic, 1.0, places=5)

    def test_ideality(self):
        m2 = {"IS": 1e-14, "N": 2.0}
        self.assertLess(devices.diode_current(0.6, m2),
                        devices.diode_current(0.6, self.MODEL))

    def test_limit_clamps_jump(self):
        old = 0.0
        new = devices.diode_limit(5.0, old, self.MODEL)
        self.assertLess(new, 1.0)          # vcrit ~ 0.7 V, not 5 V
        self.assertGreater(new, old)

    def test_limit_allows_small_step(self):
        self.assertAlmostEqual(devices.diode_limit(0.51, 0.5, self.MODEL),
                               0.51)


class TestSources(unittest.TestCase):
    def test_dc_only(self):
        el = {"kind": "V", "dc": 3.3, "wave": None}
        self.assertEqual(devices.source_value(el, 1.0), 3.3)
        self.assertEqual(devices.source_value(el, None), 3.3)

    def test_sin(self):
        el = {"kind": "V", "dc": 0.0,
              "wave": {"kind": "sin", "off": 1.0, "amp": 2.0,
                       "freq": 1000.0, "td": 0.0, "theta": 0.0}}
        self.assertAlmostEqual(devices.source_value(el, 0.0), 1.0)
        self.assertAlmostEqual(devices.source_value(el, 0.25e-3), 3.0)
        self.assertAlmostEqual(devices.source_value(el, 0.75e-3), -1.0)

    def test_sin_delay(self):
        el = {"kind": "V", "dc": 0.0,
              "wave": {"kind": "sin", "off": 0.0, "amp": 1.0,
                       "freq": 1e3, "td": 1e-3, "theta": 0.0}}
        self.assertEqual(devices.source_value(el, 0.5e-3), 0.0)
        self.assertAlmostEqual(devices.source_value(el, 1.25e-3), 1.0)

    def test_pulse(self):
        el = {"kind": "I", "dc": 0.0,
              "wave": {"kind": "pulse", "v1": 0.0, "v2": 2e-6,
                       "td": 1e-6, "tr": 10e-9, "tf": 10e-9,
                       "pw": 20e-6, "per": 40e-6}}
        self.assertEqual(devices.source_value(el, 0.0), 0.0)
        self.assertAlmostEqual(devices.source_value(el, 5e-6), 2e-6)
        self.assertAlmostEqual(devices.source_value(el, 45e-6), 2e-6)
        self.assertAlmostEqual(devices.source_value(el, 1.005e-6), 1e-6)

    def test_op_uses_dc_for_pulse(self):
        el = {"kind": "V", "dc": 0.0,
              "wave": {"kind": "pulse", "v1": 0.0, "v2": 5.0,
                       "td": 0.0, "tr": 1e-9, "tf": 1e-9,
                       "pw": 1e-3, "per": 2e-3}}
        self.assertEqual(devices.source_value(el, None), 0.0)


if __name__ == "__main__":
    unittest.main()
