from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any


class ConditionalError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ConditionalError(f"Required frozen input not found: {path}") from exc


def _weighted_line(
    x: list[float], y: list[float], sigma: list[float]
) -> tuple[float, float, float]:
    weights = [1.0 / value**2 for value in sigma]
    s0 = sum(weights)
    sx = sum(weight * value for weight, value in zip(weights, x))
    sy = sum(weight * value for weight, value in zip(weights, y))
    sxx = sum(weight * value * value for weight, value in zip(weights, x))
    sxy = sum(weight * first * second for weight, first, second in zip(weights, x, y))
    determinant = s0 * sxx - sx * sx
    if determinant <= 0:
        raise ConditionalError("Fixed-probability regression is singular")
    beta = (s0 * sxy - sx * sy) / determinant
    alpha = (sy - beta * sx) / s0
    beta_measurement_error = math.sqrt(s0 / determinant)
    return alpha, beta, beta_measurement_error


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ConditionalError("Common-gain regression is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[index][-1] for index in range(n)]


def _weighted_plane(
    probability: list[float],
    gain_proxy: list[float],
    y: list[float],
    sigma: list[float],
) -> tuple[float, float, float]:
    gain_mean = sum(gain_proxy) / len(gain_proxy)
    gain_scale = math.sqrt(
        sum((value - gain_mean) ** 2 for value in gain_proxy) / len(gain_proxy)
    )
    if gain_scale <= 0:
        raise ConditionalError(
            "Reference-band MP energy is constant; common-gain model is singular"
        )
    standardized_gain = [(value - gain_mean) / gain_scale for value in gain_proxy]
    design = [[1.0, gain, prob] for gain, prob in zip(standardized_gain, probability)]
    weights = [1.0 / value**2 for value in sigma]
    normal = [[0.0] * 3 for _ in range(3)]
    rhs = [0.0] * 3
    for row, response, weight in zip(design, y, weights):
        for first in range(3):
            rhs[first] += weight * row[first] * response
            for second in range(3):
                normal[first][second] += weight * row[first] * row[second]
    alpha, gamma_standardized, beta = _solve(normal, rhs)
    return alpha, gamma_standardized / gain_scale, beta


def run_conditional_ip(
    results_root: str | Path,
    target_observation: str,
    config: dict[str, Any],
) -> Path:
    """Run descriptive frozen-probability IP regressions without asymptotic p-values."""
    root = Path(results_root).expanduser().resolve()
    target_id = target_observation.removesuffix(".I").removesuffix(".rf")
    directory = root / "observations" / target_id
    groups = _read_csv(directory / "10_candidates" / "mp_groups_frozen.csv")
    subbands = _read_csv(directory / "09_subbands" / "n04" / "subband_metrics.csv")
    reference_band = config["subbands"].get("reference_band_index")
    if reference_band is None:
        raise ConditionalError(
            "reference_band_index must be frozen before conditional IP analysis"
        )
    probabilities = {
        int(row["subint"]): float(row["p_high"])
        for row in groups
        if row.get("reference_band_qc_pass") == "true"
        and row.get("p_high") not in (None, "")
    }
    reference_energy = {
        int(row["subint"]): float(row["mp_primary_energy"])
        for row in subbands
        if int(row["subband_index"]) == int(reference_band)
    }
    by_band: dict[int, list[dict[str, str]]] = {index: [] for index in range(4)}
    for row in subbands:
        by_band[int(row["subband_index"])].append(row)

    output_rows: list[dict[str, Any]] = []
    for band, rows in sorted(by_band.items()):
        rows = sorted(rows, key=lambda row: int(row["subint"]))
        usable = [
            row
            for row in rows
            if int(row["subint"]) in probabilities
            and int(row["subint"]) in reference_energy
            and float(row["ip_primary_error"]) > 0
        ]
        if len(usable) < 4:
            raise ConditionalError(
                f"Band {band} has only {len(usable)} usable frozen points"
            )
        subints = [int(row["subint"]) for row in usable]
        p = [probabilities[subint] for subint in subints]
        y = [float(row["ip_primary_energy"]) for row in usable]
        sigma = [float(row["ip_primary_error"]) for row in usable]
        weights_high = [prob / error**2 for prob, error in zip(p, sigma)]
        weights_low = [(1.0 - prob) / error**2 for prob, error in zip(p, sigma)]
        if sum(weights_high) <= 0 or sum(weights_low) <= 0:
            raise ConditionalError(
                f"Band {band} has zero probability weight for one state"
            )
        high_mean = sum(weight * value for weight, value in zip(weights_high, y)) / sum(
            weights_high
        )
        low_mean = sum(weight * value for weight, value in zip(weights_low, y)) / sum(
            weights_low
        )
        alpha, beta, beta_error = _weighted_line(p, y, sigma)
        gain = [reference_energy[subint] for subint in subints]
        common_alpha, common_gamma, common_beta = _weighted_plane(p, gain, y, sigma)
        output_rows.append(
            {
                "file": f"{target_id}.I",
                "subband_index": band,
                "n_points": len(usable),
                "probability_weighted_ip_high": high_mean,
                "probability_weighted_ip_low": low_mean,
                "delta_ip_high_minus_low": high_mean - low_mean,
                "fixed_probability_alpha": alpha,
                "fixed_probability_beta": beta,
                "beta_measurement_error_only": beta_error,
                "common_gain_alpha": common_alpha,
                "common_gain_gamma_mp_reference": common_gamma,
                "common_gain_beta_state": common_beta,
                "asymptotic_p_value_reported": "false",
                "inference_scope": "descriptive conditional candidate test; measurement model only",
            }
        )

    output = directory / "10_candidates" / "conditional_ip_results.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)
    return output
