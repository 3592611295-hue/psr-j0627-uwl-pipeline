from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import canonical_json
from .svg import mjd_svg


class SummaryError(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise SummaryError(f"No rows to write: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_master_summary(results_root: str | Path) -> Path:
    root = Path(results_root).expanduser().resolve()
    observation_files = sorted(
        root.glob("observations/*/10_candidates/observation_summary.csv")
    )
    event_files = sorted(root.glob("observations/*/10_candidates/candidate_events.csv"))
    qc_files = sorted(root.glob("observations/*/08_qc/subint_metrics.csv"))
    if not observation_files:
        raise SummaryError(f"No completed observation summaries found under {root}")

    observations = [row for path in observation_files for row in _read_csv(path)]
    events = [row for path in event_files for row in _read_csv(path)]
    qc_rows = [row for path in qc_files for row in _read_csv(path)]

    def assert_unique(
        rows: list[dict[str, str]], keys: tuple[str, ...], label: str
    ) -> None:
        seen: set[tuple[str, ...]] = set()
        duplicates: list[tuple[str, ...]] = []
        for row in rows:
            key = tuple(row[column] for column in keys)
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        if duplicates:
            raise SummaryError(f"Duplicate {label} keys: {duplicates[:5]}")

    assert_unique(observations, ("file",), "observation")
    assert_unique(events, ("file", "subint"), "candidate event")
    assert_unique(qc_rows, ("file", "subint"), "QC subint")

    summary_dir = root / "master_summary"
    _write_csv(summary_dir / "master_observations.csv", observations)
    _write_csv(summary_dir / "master_candidate_events.csv", events)
    _write_csv(summary_dir / "master_subint_qc.csv", qc_rows)
    mjd_svg(observations, summary_dir / "mjd_relative_energy.svg")

    role_counts = Counter(row.get("analysis_role", "") for row in observations)
    tier_counts = Counter(row.get("candidate_tier", "") for row in events)
    report = [
        "# PSR J0627+0706 Parkes/UWL master summary",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        f"- Observations: {len(observations)}",
        f"- Subintegrations: {len(events)}",
        f"- Tier A candidate events: {tier_counts.get('A', 0)}",
        f"- Tier B candidate events: {tier_counts.get('B', 0)}",
        f"- Tier C/suspect events: {tier_counts.get('C', 0)}",
        "",
        "These are candidate-evidence labels. They do not independently establish radiative mode changing.",
        "Relative energy is not an absolute flux density in mJy.",
        "",
        "## Observation roles",
        "",
    ]
    report.extend(
        f"- {role or 'unspecified'}: {count}"
        for role, count in sorted(role_counts.items())
    )
    report.append("")
    (summary_dir / "master_summary.md").write_text("\n".join(report), encoding="utf-8")
    (summary_dir / "manifest.json").write_text(
        canonical_json(
            {
                "schema_version": 1,
                "generated_utc": datetime.now(timezone.utc).isoformat(),
                "observation_inputs": [str(path) for path in observation_files],
                "candidate_inputs": [str(path) for path in event_files],
                "qc_inputs": [str(path) for path in qc_files],
            }
        ),
        encoding="utf-8",
    )
    return summary_dir
