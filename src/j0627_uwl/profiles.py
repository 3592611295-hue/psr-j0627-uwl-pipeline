from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable


Profile = list[float]
ProfileCube = dict[tuple[int, int], Profile]


class ProfileError(ValueError):
    """Raised when a text profile dump is incomplete or ambiguous."""


def _as_index(value: float) -> int:
    rounded = int(round(value))
    if abs(value - rounded) > 1e-8:
        raise ProfileError(f"Expected integer index, got {value}")
    return rounded


def parse_pdv_text(text: str, expected_nbin: int | None = None) -> ProfileCube:
    """Parse the numeric forms commonly emitted by ``pdv -t``.

    Supported rows are ``subint channel bin ... intensity``,
    ``subint bin intensity``, and ``bin intensity``. Header and diagnostic lines
    are ignored. Duplicate coordinates are rejected instead of silently pooled.
    """

    points: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            values = [float(token) for token in line.split()]
        except ValueError:
            continue

        try:
            if len(values) >= 4:
                subint = _as_index(values[0])
                channel = _as_index(values[1])
                phase_bin = _as_index(values[2])
                intensity = float(values[-1])
            elif len(values) == 3:
                subint = _as_index(values[0])
                channel = 0
                phase_bin = _as_index(values[1])
                intensity = float(values[2])
            elif len(values) == 2:
                subint = 0
                channel = 0
                phase_bin = _as_index(values[0])
                intensity = float(values[1])
            else:
                continue
        except ProfileError as exc:
            raise ProfileError(f"Line {line_number}: {exc}") from exc

        if subint < 0 or channel < 0 or phase_bin < 0 or not math.isfinite(intensity):
            continue
        key = (subint, channel)
        if phase_bin in points[key]:
            raise ProfileError(
                f"Duplicate pdv coordinate subint={subint}, channel={channel}, bin={phase_bin}"
            )
        points[key][phase_bin] = intensity

    if not points:
        raise ProfileError("No numeric profile samples were parsed from pdv output")

    observed_nbin = max(max(profile) for profile in points.values()) + 1
    nbin = expected_nbin if expected_nbin is not None else observed_nbin
    if observed_nbin > nbin:
        raise ProfileError(
            f"Observed phase bin {observed_nbin - 1} exceeds expected nbin={nbin}"
        )

    cube: ProfileCube = {}
    for key, samples in sorted(points.items()):
        missing = sorted(set(range(nbin)) - set(samples))
        if missing:
            preview = ", ".join(str(value) for value in missing[:8])
            raise ProfileError(f"Profile {key} is missing phase bins: {preview}")
        cube[key] = [samples[index] for index in range(nbin)]
    return cube


def average_profiles(profiles: Iterable[Profile]) -> Profile:
    materialized = [list(profile) for profile in profiles]
    if not materialized:
        raise ProfileError("Cannot average an empty profile collection")
    nbin = len(materialized[0])
    if any(len(profile) != nbin for profile in materialized):
        raise ProfileError("All profiles must have the same number of phase bins")
    result: Profile = []
    for phase_bin in range(nbin):
        values = [
            profile[phase_bin]
            for profile in materialized
            if math.isfinite(profile[phase_bin])
        ]
        if not values:
            raise ProfileError(f"No finite values at phase bin {phase_bin}")
        result.append(sum(values) / len(values))
    return result


def average_cube(cube: ProfileCube) -> Profile:
    return average_profiles(cube.values())


def _standardize(profile: Profile) -> Profile:
    finite = [value for value in profile if math.isfinite(value)]
    if len(finite) != len(profile):
        raise ProfileError("Circular template matching requires finite profiles")
    mean = sum(finite) / len(finite)
    variance = sum((value - mean) ** 2 for value in finite) / len(finite)
    scale = math.sqrt(variance)
    if scale <= 0:
        raise ProfileError("Cannot template-match a constant profile")
    return [(value - mean) / scale for value in profile]


def apply_circular_shift(profile: Profile, shift: int) -> Profile:
    """Return template-coordinate data where output[i] = input[i + shift]."""
    nbin = len(profile)
    if nbin == 0:
        raise ProfileError("Cannot shift an empty profile")
    normalized_shift = shift % nbin
    return [profile[(index + normalized_shift) % nbin] for index in range(nbin)]


def best_circular_alignment(reference: Profile, target: Profile) -> tuple[int, float]:
    """Find one observation-level shift; never align subints or subbands independently."""
    if len(reference) != len(target):
        raise ProfileError("Template and observation must have the same nbin")
    ref = _standardize(reference)
    obs = _standardize(target)
    nbin = len(ref)
    best_shift = 0
    best_corr = -math.inf
    for shift in range(nbin):
        correlation = (
            sum(ref[index] * obs[(index + shift) % nbin] for index in range(nbin))
            / nbin
        )
        if correlation > best_corr:
            best_corr = correlation
            best_shift = shift
    return best_shift, best_corr


def align_cube(cube: ProfileCube, shift: int) -> ProfileCube:
    return {key: apply_circular_shift(profile, shift) for key, profile in cube.items()}
