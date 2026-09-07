from __future__ import annotations

import math
from collections import Counter
from typing import Any


POSITIVE_BAND_STATES = {"robust_positive", "robust_strong"}


def band_state(row: dict[str, Any], thresholds: dict[str, Any]) -> str:
    primary = float(row["mp_primary_snr"])
    control = float(row["mp_control_snr"])
    detection = float(thresholds["subband_detect_snr"])
    strong = float(thresholds["subband_strong_snr"])
    if not math.isfinite(primary) or not math.isfinite(control):
        return "invalid"
    if primary >= strong and control >= strong:
        return "robust_strong"
    if primary >= detection and control >= detection:
        return "robust_positive"
    if primary <= -detection and control <= -detection:
        return "robust_negative"
    if primary * control < 0 and max(abs(primary), abs(control)) >= detection:
        return "sign_changed"
    if max(primary, control) >= detection:
        return "off_window_sensitive"
    return "no_or_weak"


def _contiguous(indices: list[int]) -> bool:
    return bool(indices) and indices == list(range(indices[0], indices[-1] + 1))


def classify_four_band_event(
    rows: list[dict[str, Any]], thresholds: dict[str, Any]
) -> dict[str, Any]:
    """Classify one subint using only an explicitly dedispersed four-band archive."""
    if len(rows) != 4:
        raise ValueError(
            f"Four-band classification requires exactly 4 rows, got {len(rows)}"
        )
    ordered = sorted(rows, key=lambda row: int(row["subband_index"]))
    states = [band_state(row, thresholds) for row in ordered]
    positive = [
        index for index, state in enumerate(states) if state in POSITIVE_BAND_STATES
    ]
    negative = [
        index for index, state in enumerate(states) if state == "robust_negative"
    ]
    sensitive = [
        index
        for index, state in enumerate(states)
        if state in {"sign_changed", "off_window_sensitive", "invalid"}
    ]

    if len(positive) == 4 and not negative and not sensitive:
        classification = "full_uwl_coherent_candidate"
        tier = "A"
    elif len(positive) == 3 and not negative and not sensitive:
        classification = "likely_broadband_candidate"
        tier = "B"
    elif negative or any(states[index] == "sign_changed" for index in range(4)):
        classification = "no_coherent_broadband_response"
        tier = "C"
    elif positive and all(index >= 3 for index in positive):
        classification = "high_frequency_limited_candidate"
        tier = "C"
    elif 1 <= len(positive) <= 2 and _contiguous(positive):
        classification = "frequency_selective_candidate"
        tier = "C"
    elif sensitive:
        classification = "background_sensitive_candidate"
        tier = "C"
    else:
        classification = "non_detection_or_noise"
        tier = "none"

    return {
        "subband_classification": classification,
        "candidate_tier": tier,
        "n_robust_positive_bands": len(positive),
        "n_robust_negative_bands": len(negative),
        "n_sensitive_bands": len(sensitive),
        "positive_band_indices": ";".join(str(index) for index in positive),
        "band_states": ";".join(states),
    }


def summarize_observation(
    rows: list[dict[str, Any]], annotation: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not rows:
        raise ValueError("Cannot summarize an observation with no candidate rows")
    counts = Counter(row["subband_classification"] for row in rows)
    tiers = Counter(row["candidate_tier"] for row in rows)
    role = "candidate_evidence_only"
    pool_eligible = True
    note = ""
    if annotation:
        role = str(annotation.get("analysis_role", role))
        pool_eligible = not bool(annotation.get("exclude_from_broadband_pool", False))
        note = str(annotation.get("note", ""))
    return {
        "file": rows[0]["file"],
        "mjd": rows[0]["mjd"],
        "n_subint": len(rows),
        "n_tier_a": tiers.get("A", 0),
        "n_tier_b": tiers.get("B", 0),
        "n_tier_c": tiers.get("C", 0),
        "n_full_uwl_coherent": counts.get("full_uwl_coherent_candidate", 0),
        "n_likely_broadband": counts.get("likely_broadband_candidate", 0),
        "n_frequency_selective": counts.get("frequency_selective_candidate", 0),
        "n_high_frequency_limited": counts.get("high_frequency_limited_candidate", 0),
        "n_background_sensitive": counts.get("background_sensitive_candidate", 0),
        "analysis_role": role,
        "broadband_pool_eligible": str(pool_eligible).lower(),
        "annotation": note,
    }
