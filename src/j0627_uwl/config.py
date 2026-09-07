from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a frozen analysis configuration is internally inconsistent."""


def canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def config_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Top-level configuration must be a JSON object")
    validate_config(data)
    data["_config_path"] = str(config_path)
    return data


def _window_indices(window: list[int], nbin: int) -> set[int]:
    if len(window) != 2 or not all(isinstance(value, int) for value in window):
        raise ConfigError(f"Window must contain two integer bins: {window!r}")
    start, end = window
    if not (0 <= start < nbin and 0 <= end < nbin):
        raise ConfigError(f"Window {window!r} lies outside 0..{nbin - 1}")
    if start == end:
        raise ConfigError(f"Half-open window must not be empty: {window!r}")
    if start < end:
        return set(range(start, end))
    return set(range(start, nbin)) | set(range(0, end))


def validate_config(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")

    archive = data.get("archive", {})
    nbin = archive.get("expected_nbin")
    if not isinstance(nbin, int) or nbin < 8:
        raise ConfigError("archive.expected_nbin must be an integer >= 8")

    windows = data.get("phase_windows", {})
    required_windows = ("mp", "ip_test", "off_primary", "off_control")
    index_sets: dict[str, set[int]] = {}
    for name in required_windows:
        if name not in windows:
            raise ConfigError(f"Missing phase_windows.{name}")
        index_sets[name] = _window_indices(windows[name], nbin)

    for pulse_name in ("mp", "ip_test"):
        for off_name in ("off_primary", "off_control"):
            if index_sets[pulse_name] & index_sets[off_name]:
                raise ConfigError(f"phase_windows.{pulse_name} overlaps {off_name}")
    if index_sets["off_primary"] & index_sets["off_control"]:
        raise ConfigError("The two off-pulse windows must not overlap")
    if index_sets["mp"] & index_sets["ip_test"]:
        raise ConfigError("MP and candidate-IP windows must not overlap")

    subbands = data.get("subbands", {})
    counts = subbands.get("counts")
    if not isinstance(counts, list) or 4 not in counts:
        raise ConfigError("subbands.counts must be a list containing 4")
    if any(not isinstance(value, int) or value < 2 for value in counts):
        raise ConfigError("Every subband count must be an integer >= 2")

    full_band = subbands.get("full_band_mhz")
    if (
        not isinstance(full_band, list)
        or len(full_band) != 2
        or not all(isinstance(value, (int, float)) for value in full_band)
        or full_band[0] >= full_band[1]
    ):
        raise ConfigError("subbands.full_band_mhz must be [low, high]")
    band_tolerance = subbands.get("band_tolerance_mhz", 1.0)
    if not isinstance(band_tolerance, (int, float)) or band_tolerance <= 0:
        raise ConfigError("subbands.band_tolerance_mhz must be positive")

    four_edges = subbands.get("four_edges_mhz")
    if (
        not isinstance(four_edges, list)
        or len(four_edges) != 5
        or any(four_edges[index] >= four_edges[index + 1] for index in range(4))
        or abs(float(four_edges[0]) - float(full_band[0])) > 1e-6
        or abs(float(four_edges[-1]) - float(full_band[1])) > 1e-6
    ):
        raise ConfigError(
            "subbands.four_edges_mhz must be five increasing full-band edges"
        )

    reference_band = subbands.get("reference_band_index")
    if reference_band is not None and reference_band not in range(4):
        raise ConfigError("reference_band_index must be null or one of 0, 1, 2, 3")

    thresholds = data.get("thresholds", {})
    state = thresholds.get("fullband_state_snr", {})
    values = [state.get(name) for name in ("low_snr", "weak", "strong")]
    if any(not isinstance(value, (int, float)) for value in values):
        raise ConfigError("fullband state thresholds must be numeric")
    if not values[0] < values[1] < values[2]:
        raise ConfigError("Require low_snr < weak < strong")

    candidate = thresholds.get("candidate", {})
    if candidate.get("four_band_full") not in (4,):
        raise ConfigError("candidate.four_band_full must be 4")
    if candidate.get("four_band_likely") not in (3,):
        raise ConfigError("candidate.four_band_likely must be 3")

    classifier = data.get("external_classifier", {})
    if classifier.get("hard_high_probability", 0) <= classifier.get(
        "hard_low_probability", 1
    ):
        raise ConfigError(
            "Classifier high-probability threshold must exceed low threshold"
        )
    component_weight = classifier.get("minimum_component_weight", 0.1)
    if (
        not isinstance(component_weight, (int, float))
        or not 0 < component_weight <= 0.5
    ):
        raise ConfigError("minimum_component_weight must lie in (0, 0.5]")


def public_config(data: dict[str, Any]) -> dict[str, Any]:
    """Return configuration without loader-only fields."""
    return {key: value for key, value in data.items() if not key.startswith("_")}
