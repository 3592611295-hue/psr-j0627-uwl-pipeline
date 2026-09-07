from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .profiles import Profile


@dataclass(frozen=True)
class WindowMeasurement:
    energy: float
    error: float
    snr: float
    baseline_mean: float
    baseline_rms: float
    on_n: int
    off_n: int

    def as_dict(self, prefix: str) -> dict[str, float | int]:
        return {f"{prefix}_{key}": value for key, value in asdict(self).items()}


def window_indices(window: list[int] | tuple[int, int], nbin: int) -> list[int]:
    start, end = int(window[0]), int(window[1])
    if not (0 <= start < nbin and 0 <= end < nbin):
        raise ValueError(f"Window {window!r} lies outside 0..{nbin - 1}")
    if start == end:
        raise ValueError(f"Half-open window must not be empty: {window!r}")
    if start < end:
        return list(range(start, end))
    return list(range(start, nbin)) + list(range(0, end))


def measure_window(
    profile: Profile,
    on_window: list[int] | tuple[int, int],
    off_window: list[int] | tuple[int, int],
) -> WindowMeasurement:
    on = [profile[index] for index in window_indices(on_window, len(profile))]
    off = [profile[index] for index in window_indices(off_window, len(profile))]
    if not on or len(off) < 2 or not all(math.isfinite(value) for value in on + off):
        raise ValueError(
            "Window measurement requires finite on-pulse data and >=2 off-pulse bins"
        )
    baseline = sum(off) / len(off)
    variance = sum((value - baseline) ** 2 for value in off) / (len(off) - 1)
    rms = math.sqrt(max(variance, 0.0))
    energy = sum(value - baseline for value in on)
    # Includes both summed sample noise and uncertainty in the estimated off mean.
    error = rms * math.sqrt(len(on) * (1.0 + len(on) / len(off)))
    snr = energy / error if error > 0 else math.nan
    return WindowMeasurement(energy, error, snr, baseline, rms, len(on), len(off))


def state_from_snr(snr: float, thresholds: dict[str, float]) -> str:
    if not math.isfinite(snr) or snr < thresholds["low_snr"]:
        return "bad_or_non_detection"
    if snr < thresholds["weak"]:
        return "low_snr"
    if snr < thresholds["strong"]:
        return "weak"
    return "strong"


def off_window_stability(
    primary: WindowMeasurement,
    control: WindowMeasurement,
    detection_snr: float,
    strong_snr: float,
    max_snr_delta: float,
) -> str:
    first, second = primary.snr, control.snr
    if not math.isfinite(first) or not math.isfinite(second):
        return "invalid"
    if first >= detection_snr and second >= detection_snr:
        return "positive_in_both_off_windows"
    if first <= -detection_snr and second <= -detection_snr:
        return "negative_in_both_off_windows"
    if (
        primary.energy * control.energy < 0
        and max(abs(first), abs(second)) >= detection_snr
    ):
        return "sign_changed"
    one_strong = max(first, second) >= strong_snr
    other_not_detected = min(first, second) < detection_snr
    if one_strong and other_not_detected:
        return "off_window_sensitive_detection"
    if (
        abs(first - second) > max_snr_delta
        and max(abs(first), abs(second)) >= detection_snr
    ):
        return "off_window_sensitive_detection"
    return "weak_in_both"


def rms_ratio(first: WindowMeasurement, second: WindowMeasurement) -> float:
    low = min(first.baseline_rms, second.baseline_rms)
    high = max(first.baseline_rms, second.baseline_rms)
    return high / low if low > 0 else math.inf
