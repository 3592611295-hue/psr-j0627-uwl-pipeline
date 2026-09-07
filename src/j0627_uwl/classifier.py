from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import canonical_json


class ClassifierError(RuntimeError):
    pass


@dataclass(frozen=True)
class Gaussian:
    weight: float
    mean: float
    variance: float


def _log_normal(value: float, mean: float, variance: float) -> float:
    return -0.5 * (math.log(2.0 * math.pi * variance) + (value - mean) ** 2 / variance)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _single_gaussian(
    values: list[float], variance_floor: float
) -> tuple[Gaussian, float]:
    mean = sum(values) / len(values)
    variance = max(
        sum((value - mean) ** 2 for value in values) / len(values), variance_floor
    )
    model = Gaussian(1.0, mean, variance)
    log_likelihood = sum(_log_normal(value, mean, variance) for value in values)
    return model, log_likelihood


def _two_gaussians(
    values: list[float], variance_floor: float = 0.05, max_iterations: int = 500
) -> tuple[list[Gaussian], float]:
    _, single_ll = _single_gaussian(values, variance_floor)
    overall_mean = sum(values) / len(values)
    overall_variance = max(
        sum((value - overall_mean) ** 2 for value in values) / len(values),
        variance_floor,
    )
    components = [
        Gaussian(0.5, _quantile(values, 0.25), overall_variance),
        Gaussian(0.5, _quantile(values, 0.75), overall_variance),
    ]
    previous = single_ll
    for _ in range(max_iterations):
        responsibilities: list[tuple[float, float]] = []
        log_likelihood = 0.0
        for value in values:
            logs = [
                math.log(max(component.weight, 1e-12))
                + _log_normal(value, component.mean, component.variance)
                for component in components
            ]
            maximum = max(logs)
            denominator = sum(math.exp(item - maximum) for item in logs)
            log_likelihood += maximum + math.log(denominator)
            responsibilities.append(
                (
                    math.exp(logs[0] - maximum) / denominator,
                    math.exp(logs[1] - maximum) / denominator,
                )
            )

        updated: list[Gaussian] = []
        for index in range(2):
            total = sum(row[index] for row in responsibilities)
            if total <= 1e-8:
                raise ClassifierError(
                    "Two-Gaussian fit collapsed to an empty component"
                )
            mean = (
                sum(row[index] * value for row, value in zip(responsibilities, values))
                / total
            )
            variance = max(
                sum(
                    row[index] * (value - mean) ** 2
                    for row, value in zip(responsibilities, values)
                )
                / total,
                variance_floor,
            )
            updated.append(Gaussian(total / len(values), mean, variance))
        components = sorted(updated, key=lambda component: component.mean)
        if abs(log_likelihood - previous) < 1e-9 * (1.0 + abs(log_likelihood)):
            break
        previous = log_likelihood

    final_ll = 0.0
    for value in values:
        logs = [
            math.log(max(component.weight, 1e-12))
            + _log_normal(value, component.mean, component.variance)
            for component in components
        ]
        maximum = max(logs)
        final_ll += maximum + math.log(sum(math.exp(item - maximum) for item in logs))
    return components, final_ll


def fit_external_classifier(
    values: list[float], settings: dict[str, Any]
) -> dict[str, Any]:
    if len(values) < 2:
        raise ClassifierError("At least two finite values are required")
    if not all(math.isfinite(value) for value in values):
        raise ClassifierError("Classifier features must be finite")
    variance_floor = float(settings.get("variance_floor", 0.05))
    single, single_ll = _single_gaussian(values, variance_floor)
    components, mixture_ll = _two_gaussians(values, variance_floor)
    n = len(values)
    bic_single = 2 * math.log(n) - 2 * single_ll
    bic_mixture = 5 * math.log(n) - 2 * mixture_ll
    delta_bic = bic_single - bic_mixture
    separation = (components[1].mean - components[0].mean) / math.sqrt(
        0.5 * (components[0].variance + components[1].variance)
    )
    accepted = (
        delta_bic >= float(settings["minimum_delta_bic"])
        and separation >= float(settings["minimum_component_separation"])
        and min(component.weight for component in components)
        >= float(settings.get("minimum_component_weight", 0.1))
    )
    return {
        "model": "two_component_gaussian",
        "accepted": accepted,
        "n_training_rows": n,
        "single_gaussian": {
            "mean": single.mean,
            "variance": single.variance,
            "log_likelihood": single_ll,
            "bic": bic_single,
        },
        "two_gaussian": {
            "components": [component.__dict__ for component in components],
            "log_likelihood": mixture_ll,
            "bic": bic_mixture,
        },
        "delta_bic_single_minus_two": delta_bic,
        "component_separation": separation,
        "acceptance_thresholds": {
            "minimum_delta_bic": float(settings["minimum_delta_bic"]),
            "minimum_component_separation": float(
                settings["minimum_component_separation"]
            ),
            "minimum_component_weight": float(
                settings.get("minimum_component_weight", 0.1)
            ),
        },
    }


def posterior_high(value: float, model: dict[str, Any]) -> float:
    components = model["two_gaussian"]["components"]
    logs = [
        math.log(max(float(component["weight"]), 1e-12))
        + _log_normal(value, float(component["mean"]), float(component["variance"]))
        for component in components
    ]
    maximum = max(logs)
    probabilities = [math.exp(item - maximum) for item in logs]
    return probabilities[1] / sum(probabilities)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_reference_rows(
    results_root: Path, reference_band: int
) -> tuple[list[dict[str, str]], list[Path]]:
    paths = sorted(
        results_root.glob("observations/*/09_subbands/n04/subband_metrics.csv")
    )
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if int(row["subband_index"]) == reference_band:
                    row["_source_metrics"] = str(path)
                    rows.append(row)
    return rows, paths


def _reference_qc_pass(row: dict[str, str], config: dict[str, Any]) -> bool:
    dual = config["thresholds"]["dual_off"]
    return (
        row.get("fullband_qc_pass") == "true"
        and row.get("off_window_stability")
        not in {"invalid", "sign_changed", "off_window_sensitive_detection"}
        and float(row.get("off_rms_ratio", "inf")) <= float(dual["max_rms_ratio"])
        and math.isfinite(float(row["mp_primary_snr"]))
    )


def freeze_target_groups(
    results_root: str | Path,
    target_observation: str,
    config: dict[str, Any],
    *,
    replace: bool = False,
) -> Path:
    root = Path(results_root).expanduser().resolve()
    settings = config["external_classifier"]
    reference_band = config["subbands"].get("reference_band_index")
    if not settings.get("enabled", False):
        raise ClassifierError(
            "Set external_classifier.enabled=true only after freezing the analysis design"
        )
    if reference_band is None:
        raise ClassifierError(
            "Freeze subbands.reference_band_index from QC metrics before training; MP/IP separation may not be used"
        )
    target_id = target_observation.removesuffix(".I").removesuffix(".rf")
    target_file = f"{target_id}.I"
    all_rows, source_paths = _load_reference_rows(root, int(reference_band))
    target_rows = [row for row in all_rows if row["file"] == target_file]
    training_rows = [
        row
        for row in all_rows
        if row["file"] != target_file and _reference_qc_pass(row, config)
    ]
    if not target_rows:
        raise ClassifierError(
            f"No four-band reference-band rows found for {target_file}"
        )
    observations = sorted({row["file"] for row in training_rows})
    if len(training_rows) < int(settings["minimum_training_rows"]):
        raise ClassifierError(
            f"Only {len(training_rows)} leave-one-observation-out training rows; "
            f"need {settings['minimum_training_rows']}"
        )
    if len(observations) < int(settings["minimum_training_observations"]):
        raise ClassifierError(
            f"Only {len(observations)} training observations; need {settings['minimum_training_observations']}"
        )

    model = fit_external_classifier(
        [float(row["mp_primary_snr"]) for row in training_rows], settings
    )
    model.update(
        {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "feature": "reference-band MP S/N",
            "reference_band_index": reference_band,
            "target_observation_excluded": target_file,
            "training_observations": observations,
            "hmm_used": False,
            "single_file_median_split_used": False,
        }
    )
    output_dir = root / "observations" / target_id / "10_candidates"
    output_dir.mkdir(parents=True, exist_ok=True)
    if not model["accepted"]:
        rejected = output_dir / "external_classifier_rejected.json"
        rejected.write_text(canonical_json(model), encoding="utf-8")
        raise ClassifierError(
            f"Two-component model did not pass frozen BIC/separation criteria; diagnostics: {rejected}"
        )

    frozen_path = output_dir / "mp_groups_frozen.csv"
    model_path = output_dir / "external_mp_classifier.json"
    training_path = output_dir / "external_classifier_training_files.csv"
    checksums_path = output_dir / "external_classifier_checksums.txt"
    for path in (frozen_path, model_path, training_path, checksums_path):
        if path.exists() and not replace:
            raise ClassifierError(
                f"Frozen output already exists and will not be overwritten: {path}"
            )

    high_threshold = float(settings["hard_high_probability"])
    low_threshold = float(settings["hard_low_probability"])
    frozen_rows: list[dict[str, Any]] = []
    for row in sorted(target_rows, key=lambda item: int(item["subint"])):
        feature = float(row["mp_primary_snr"])
        qc_pass = _reference_qc_pass(row, config)
        if qc_pass:
            probability: float | str = posterior_high(feature, model)
            if probability >= high_threshold:
                label = "MP-high"
            elif probability <= low_threshold:
                label = "MP-low"
            else:
                label = "uncertain"
        else:
            probability = ""
            label = "excluded_qc"
        frozen_rows.append(
            {
                "file": row["file"],
                "mjd": row["mjd"],
                "subint": row["subint"],
                "reference_band_index": reference_band,
                "mp_snr_reference_band": feature,
                "p_high": probability,
                "p_low": 1.0 - probability if isinstance(probability, float) else "",
                "hard_label_for_plotting_only": label,
                "reference_band_qc_pass": str(qc_pass).lower(),
                "target_excluded_from_training": "true",
            }
        )
    with frozen_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frozen_rows[0]))
        writer.writeheader()
        writer.writerows(frozen_rows)
    model_path.write_text(canonical_json(model), encoding="utf-8")
    with training_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "n_rows"])
        writer.writeheader()
        for observation in observations:
            writer.writerow(
                {
                    "file": observation,
                    "n_rows": sum(row["file"] == observation for row in training_rows),
                }
            )
    unique_sources = sorted({Path(row["_source_metrics"]) for row in training_rows})
    checksums_path.write_text(
        "\n".join(f"{_sha256(path)}  {path}" for path in unique_sources) + "\n",
        encoding="utf-8",
    )
    return frozen_path
