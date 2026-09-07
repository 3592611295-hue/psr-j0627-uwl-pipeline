import unittest

from j0627_uwl.classify import classify_four_band_event


THRESHOLDS = {"subband_detect_snr": 3.0, "subband_strong_snr": 5.0}


def row(index, primary, control):
    return {
        "subband_index": index,
        "mp_primary_snr": primary,
        "mp_control_snr": control,
    }


class CandidateTests(unittest.TestCase):
    def test_four_positive_bands_are_tier_a(self):
        result = classify_four_band_event(
            [row(index, 6, 6) for index in range(4)], THRESHOLDS
        )
        self.assertEqual(
            result["subband_classification"], "full_uwl_coherent_candidate"
        )
        self.assertEqual(result["candidate_tier"], "A")

    def test_only_top_band_is_high_frequency_limited(self):
        rows = [row(0, 0, 0), row(1, 0, 0), row(2, 0, 0), row(3, 6, 6)]
        result = classify_four_band_event(rows, THRESHOLDS)
        self.assertEqual(
            result["subband_classification"], "high_frequency_limited_candidate"
        )
        self.assertEqual(result["candidate_tier"], "C")

    def test_sign_inconsistency_is_not_broadband(self):
        rows = [row(0, 6, 6), row(1, 6, 6), row(2, -6, -6), row(3, 0, 0)]
        result = classify_four_band_event(rows, THRESHOLDS)
        self.assertEqual(
            result["subband_classification"], "no_coherent_broadband_response"
        )


if __name__ == "__main__":
    unittest.main()
