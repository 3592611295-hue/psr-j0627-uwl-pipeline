import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from j0627_uwl.bref import build_reference_band_qc_report
from j0627_uwl.config import load_config
from j0627_uwl.pipeline import run_observation
from j0627_uwl.profiles import apply_circular_shift
from j0627_uwl.psrchive import CommandResult
from j0627_uwl.summary import build_master_summary


ROOT = Path(__file__).resolve().parents[1]


def synthetic_template():
    profile = [0.1 if index % 2 else -0.1 for index in range(1024)]
    for index in range(465, 525):
        profile[index] += 10.0 - abs(index - 495) / 5.0
    return profile


class FakePSRCHIVE:
    def __init__(self):
        self.template = synthetic_template()
        self.observation = apply_circular_shift(self.template, -137)

    @staticmethod
    def _pdv(profiles):
        lines = []
        for (subint, channel), profile in sorted(profiles.items()):
            lines.extend(
                f"{subint} {channel} {index} {value}"
                for index, value in enumerate(profile)
            )
        return "\n".join(lines) + "\n"

    def run(self, runner, args, cwd=None, capture_path=None, allow_failure=False):
        command = [str(arg) for arg in args]
        stdout = "ok\n"
        if command[0] == "paz":
            output_dir = Path(command[command.index("-O") + 1])
            source = Path(command[-1])
            (output_dir / f"{source.stem}.zap").write_text("fake", encoding="utf-8")
        elif command[0] == "pam" and "--version" in command:
            stdout = "pam fake-version\n"
        elif command[0] == "pam":
            output_dir = Path(command[command.index("-u") + 1])
            extension = command[command.index("-e") + 1]
            source = Path(command[-1])
            (output_dir / f"{source.stem}.{extension}").write_text(
                "fake", encoding="utf-8"
            )
        elif command[0] == "psrplot":
            device = command[command.index("-D") + 1]
            output = Path(device.removesuffix("/gif"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"GIF89a")
        elif command[0] == "pdv":
            archive = Path(command[-1])
            if archive.suffix == ".FTp":
                stdout = self._pdv({(0, 0): self.template})
            elif archive.suffix == ".I":
                stdout = self._pdv(
                    {
                        (0, 0): self.observation,
                        (1, 0): [value * 1.2 for value in self.observation],
                    }
                )
            else:
                count = int(archive.suffix.removeprefix(".I").removesuffix("D"))
                cube = {}
                for subint in range(2):
                    for channel in range(count):
                        scale = (1.0 + 0.1 * channel) * (1.0 + 0.2 * subint)
                        cube[(subint, channel)] = [
                            value * scale for value in self.observation
                        ]
                stdout = self._pdv(cube)
        elif command[0] == "psredit" and "-Qqc" in command:
            expression = command[command.index("-Qqc") + 1]
            archive = Path(command[-1])
            if expression.startswith("int[0]:mjd"):
                stdout = "60222.761868\n"
            elif expression == "dmc":
                stdout = "1\n"
            elif expression == "nchan":
                if archive.suffix == ".I":
                    stdout = "1\n"
                else:
                    stdout = archive.suffix.removeprefix(".I").removesuffix("D") + "\n"
            elif expression == "bw":
                stdout = "-3328\n"
            elif expression == "freq":
                stdout = "2368\n"
        if capture_path is not None:
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_text(stdout, encoding="utf-8")
        return CommandResult(command, 0, stdout, "")


class PipelineIntegrationTests(unittest.TestCase):
    def test_end_to_end_with_fake_psrchive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "uwl_231005_181706.rf"
            template = root / "uwl_220604_024229.FTp"
            raw.write_text("fake", encoding="utf-8")
            template.write_text("fake", encoding="utf-8")
            config_data = json.loads(
                (ROOT / "configs" / "j0627_uwl.example.json").read_text(
                    encoding="utf-8"
                )
            )
            config_data["archive"]["template"] = str(template)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(config_data), encoding="utf-8")
            config = load_config(config_path)
            fake = FakePSRCHIVE()

            with (
                patch("j0627_uwl.pipeline.require_tools"),
                patch(
                    "j0627_uwl.psrchive.CommandRunner.run",
                    autospec=True,
                    side_effect=fake.run,
                ),
            ):
                output = run_observation(config, raw, root / "results")

            candidate_path = output / "10_candidates" / "candidate_events.csv"
            with candidate_path.open(newline="", encoding="utf-8") as handle:
                candidates = list(csv.DictReader(handle))
            self.assertEqual(len(candidates), 2)
            self.assertTrue(all(row["candidate_tier"] == "A" for row in candidates))
            self.assertTrue(
                (output / "09_subbands" / "n04" / "provenance.json").exists()
            )
            with (output / "09_subbands" / "n04" / "subband_metrics.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                bands = list(csv.DictReader(handle))
            raw_channel_zero = next(
                row for row in bands if row["archive_channel_index"] == "0"
            )
            self.assertEqual(raw_channel_zero["subband_index"], "3")
            self.assertEqual(raw_channel_zero["freq_low_mhz"], "3200.000000")
            summary = build_master_summary(root / "results")
            self.assertTrue((summary / "master_observations.csv").exists())
            self.assertTrue((summary / "mjd_relative_energy.svg").exists())
            bref = build_reference_band_qc_report(root / "results")
            with bref.open(newline="", encoding="utf-8") as handle:
                bref_rows = list(csv.DictReader(handle))
            self.assertEqual(len(bref_rows), 4)
            self.assertTrue(
                all(
                    row["mp_or_ip_response_used_for_selection"] == "false"
                    for row in bref_rows
                )
            )


if __name__ == "__main__":
    unittest.main()
