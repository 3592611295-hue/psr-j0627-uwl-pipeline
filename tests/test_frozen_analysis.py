import csv
import json
import tempfile
import unittest
from pathlib import Path

from j0627_uwl.classifier import freeze_target_groups
from j0627_uwl.conditional import run_conditional_ip
from j0627_uwl.config import load_config


ROOT = Path(__file__).resolve().parents[1]


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FrozenAnalysisTests(unittest.TestCase):
    def _config(self, root):
        data = json.loads(
            (ROOT / "configs" / "j0627_uwl.example.json").read_text(encoding="utf-8")
        )
        data["archive"]["template"] = str(root / "unused.FTp")
        data["subbands"]["reference_band_index"] = 0
        data["external_classifier"]["enabled"] = True
        data["external_classifier"]["minimum_training_rows"] = 20
        path = root / "config.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return load_config(path)

    def test_leave_target_out_freeze_and_conditional_regression(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            results = root / "results"
            config = self._config(root)

            for observation in range(4):
                rows = []
                for subint in range(10):
                    feature = (
                        -2.0 + 0.02 * subint if subint < 5 else 5.0 + 0.02 * subint
                    )
                    rows.append(
                        {
                            "file": f"train_{observation}.I",
                            "mjd": 60000 + observation,
                            "subint": subint,
                            "subband_index": 0,
                            "fullband_qc_pass": "true",
                            "off_window_stability": "positive_in_both_off_windows",
                            "off_rms_ratio": 1.0,
                            "mp_primary_snr": feature,
                        }
                    )
                write_csv(
                    results
                    / "observations"
                    / f"train_{observation}"
                    / "09_subbands"
                    / "n04"
                    / "subband_metrics.csv",
                    rows,
                )

            target_features = [-2.0, -1.8, 4.9, 5.1, 0.5]
            fixed_probabilities = [0.0, 0.1, 0.8, 1.0, 0.5]
            gain_values = [1, 4, 2, 5, 3]
            target_rows = []
            for subint, feature in enumerate(target_features):
                for band in range(4):
                    target_rows.append(
                        {
                            "file": "target.I",
                            "mjd": 60222.0,
                            "subint": subint,
                            "subband_index": band,
                            "fullband_qc_pass": "true",
                            "off_window_stability": "positive_in_both_off_windows",
                            "off_rms_ratio": 1.0,
                            "mp_primary_snr": feature,
                            "mp_primary_energy": gain_values[subint],
                            "ip_primary_energy": 5
                            + 0.5 * gain_values[subint]
                            + 2.0 * fixed_probabilities[subint],
                            "ip_primary_error": 1.0,
                        }
                    )
            target_metrics = (
                results
                / "observations"
                / "target"
                / "09_subbands"
                / "n04"
                / "subband_metrics.csv"
            )
            write_csv(target_metrics, target_rows)
            frozen = freeze_target_groups(results, "target", config)
            with frozen.open(newline="", encoding="utf-8") as handle:
                groups = list(csv.DictReader(handle))
            self.assertEqual(len(groups), 5)
            self.assertTrue(
                all(row["target_excluded_from_training"] == "true" for row in groups)
            )

            # Use deterministic frozen probabilities to isolate the regression test.
            for row, probability in zip(groups, fixed_probabilities):
                row["p_high"] = probability
                row["p_low"] = 1.0 - probability
            write_csv(frozen, groups)
            conditional = run_conditional_ip(results, "target", config)
            with conditional.open(newline="", encoding="utf-8") as handle:
                regression = list(csv.DictReader(handle))
            self.assertEqual(len(regression), 4)
            for row in regression:
                self.assertAlmostEqual(
                    float(row["common_gain_beta_state"]), 2.0, places=8
                )
                self.assertEqual(row["asymptotic_p_value_reported"], "false")


if __name__ == "__main__":
    unittest.main()
