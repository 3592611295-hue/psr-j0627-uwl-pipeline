import math
import unittest

from j0627_uwl.metrics import measure_window, off_window_stability, window_indices


class MetricTests(unittest.TestCase):
    def test_wraparound_window_is_half_open(self):
        self.assertEqual(window_indices([14, 1], 16), [14, 15, 0])

    def test_energy_error_includes_baseline_uncertainty(self):
        profile = [0.0] * 16
        profile[2:4] = [5.0, 5.0]
        profile[8:12] = [-1.0, 1.0, -1.0, 1.0]
        result = measure_window(profile, [2, 4], [8, 12])
        self.assertAlmostEqual(result.energy, 10.0)
        expected_rms = math.sqrt(4.0 / 3.0)
        self.assertAlmostEqual(result.baseline_rms, expected_rms)
        self.assertAlmostEqual(result.error, expected_rms * math.sqrt(3.0))

    def test_sign_change_is_flagged(self):
        profile = [0.0] * 20
        profile[2:4] = [5.0, 5.0]
        profile[8:12] = [-1.0, 1.0, -1.0, 1.0]
        profile[14:18] = [9.0, 11.0, 9.0, 11.0]
        primary = measure_window(profile, [2, 4], [8, 12])
        control = measure_window(profile, [2, 4], [14, 18])
        self.assertEqual(
            off_window_stability(primary, control, 3.0, 5.0, 5.0), "sign_changed"
        )


if __name__ == "__main__":
    unittest.main()
