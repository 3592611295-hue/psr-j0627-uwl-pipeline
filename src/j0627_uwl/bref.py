from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any


class ReferenceBandError(RuntimeError):
    pass


def build_reference_band_qc_report(results_root: str | Path) -> Path:
    """Summarize QC quantities without inspecting MP separation or IP response."""
    root = Path(results_root).expanduser().resolve()
    paths = sorted(root.glob("observations/*/09_subbands/n04/subband_metrics.csv"))
    if not paths:
        raise ReferenceBandError(f"No four-band metric tables found under {root}")
    by_band: dict[int, list[dict[str, str]]] = {index: [] for index in range(4)}
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                by_band[int(row["subband_index"])].append(row)

    report: list[dict[str, Any]] = []
    unstable = {"invalid", "sign_changed", "off_window_sensitive_detection"}
    for band, rows in sorted(by_band.items()):
        finite = [
            row
            for row in rows
            if math.isfinite(float(row["mp_primary_baseline_rms"]))
            and math.isfinite(float(row["mp_control_baseline_rms"]))
        ]
        if not finite:
            raise ReferenceBandError(f"No finite QC measurements for band {band}")
        report.append(
            {
                "subband_index_low_to_high": band,
                "freq_low_mhz": finite[0]["freq_low_mhz"],
                "freq_high_mhz": finite[0]["freq_high_mhz"],
                "n_profiles": len(rows),
                "finite_profile_fraction": len(finite) / len(rows),
                "fullband_qc_pass_fraction": sum(
                    row.get("fullband_qc_pass") == "true" for row in finite
                )
                / len(finite),
                "dual_off_stable_fraction": sum(
                    row.get("off_window_stability") not in unstable for row in finite
                )
                / len(finite),
                "median_primary_off_rms": statistics.median(
                    float(row["mp_primary_baseline_rms"]) for row in finite
                ),
                "median_control_off_rms": statistics.median(
                    float(row["mp_control_baseline_rms"]) for row in finite
                ),
                "median_off_rms_ratio": statistics.median(
                    float(row["off_rms_ratio"]) for row in finite
                ),
                "mp_or_ip_response_used_for_selection": "false",
                "selection_status": "review_then_freeze_in_config",
            }
        )
    output = root / "master_summary" / "reference_band_qc_report.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report[0]))
        writer.writeheader()
        writer.writerows(report)
    return output
