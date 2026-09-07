from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .classify import classify_four_band_event, summarize_observation
from .config import canonical_json, config_hash, public_config
from .metrics import measure_window, off_window_stability, rms_ratio, state_from_snr
from .profiles import align_cube, average_cube, best_circular_alignment, parse_pdv_text
from .psrchive import (
    CommandError,
    CommandRunner,
    dump_profiles,
    make_plots,
    make_subbands,
    make_total_intensity,
    make_zap,
    query_float,
    query_integer,
    query_mjd,
    require_tools,
    write_archive_checks,
)
from .svg import profile_svg


class PipelineError(RuntimeError):
    """Raised when a reduction invariant is not satisfied."""


STAGE_NAMES = (
    "00_manifest",
    "01_checks",
    "02_raw_plots",
    "03_zap",
    "04_zap_plots",
    "05_total_intensity",
    "06_profiles",
    "07_template_match",
    "08_qc",
    "09_subbands",
    "10_candidates",
    "logs",
)


def _write_csv(
    path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fieldnames:
        raise PipelineError(f"Cannot infer CSV columns for empty output: {path}")
    columns = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(data), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _window_label(window: list[int]) -> str:
    return f"{window[0]}-{window[1]}"


def _expected_edges(full_band: list[float], count: int) -> list[float]:
    low, high = map(float, full_band)
    width = (high - low) / count
    return [low + index * width for index in range(count + 1)]


class ObservationPipeline:
    def __init__(
        self,
        config: dict[str, Any],
        raw_archive: Path,
        output_root: Path,
        *,
        dry_run: bool = False,
        resume: bool = False,
        hash_inputs: bool = False,
    ):
        self.config = config
        self.raw_archive = raw_archive.expanduser().resolve()
        self.output_root = output_root.expanduser().resolve()
        self.obs_id = self.raw_archive.stem
        self.root = self.output_root / "observations" / self.obs_id
        self.dry_run = dry_run
        self.resume = resume
        self.hash_inputs = hash_inputs
        self.stages = {name: self.root / name for name in STAGE_NAMES}
        self.runner = CommandRunner(
            self.stages["logs"] / "commands.jsonl", dry_run=dry_run
        )

    def _prepare(self) -> None:
        if self.raw_archive.suffix.lower() != ".rf":
            raise PipelineError(f"Input must be a .rf archive: {self.raw_archive}")
        if not self.raw_archive.exists():
            raise PipelineError(f"Raw archive not found: {self.raw_archive}")
        if self.root.exists() and any(self.root.iterdir()) and not self.resume:
            raise PipelineError(
                f"Output already exists: {self.root}. Use --resume only after checking the frozen config."
            )
        for directory in self.stages.values():
            directory.mkdir(parents=True, exist_ok=True)

        frozen_path = self.stages["00_manifest"] / "config.frozen.json"
        frozen = public_config(self.config)
        if frozen_path.exists():
            existing = json.loads(frozen_path.read_text(encoding="utf-8"))
            if existing != frozen:
                raise PipelineError(
                    "Existing observation uses a different frozen config; choose a new output root instead of overwriting it"
                )
        else:
            frozen_path.write_text(canonical_json(frozen), encoding="utf-8")

        stat = self.raw_archive.stat()
        input_record: dict[str, Any] = {
            "path": str(self.raw_archive),
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        if self.hash_inputs:
            input_record["sha256"] = _sha256(self.raw_archive)
        _write_json(
            self.stages["00_manifest"] / "run_manifest.json",
            {
                "schema_version": 1,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "observation_id": self.obs_id,
                "input": input_record,
                "config_sha256": config_hash(frozen),
                "dry_run": self.dry_run,
                "resume": self.resume,
                "scientific_scope": self.config["project"]["result_scope"],
            },
        )

    def _template_path(self) -> Path:
        configured = Path(self.config["archive"]["template"]).expanduser()
        if not configured.is_absolute():
            config_dir = Path(self.config.get("_config_path", ".")).resolve().parent
            configured = config_dir / configured
        return configured.resolve()

    def _assert_dedispersed(
        self, archive: Path, expected_nchan: int, *, check_full_band: bool = True
    ) -> dict[str, int | float]:
        dmc = query_integer(self.runner, archive, "dmc")
        nchan = query_integer(self.runner, archive, "nchan")
        bandwidth = query_float(self.runner, archive, "bw")
        centre_frequency = query_float(self.runner, archive, "freq")
        if dmc != 1:
            raise PipelineError(
                f"Dedispersion invariant failed for {archive}: dmc={dmc}. Subband analysis is forbidden."
            )
        if nchan != expected_nchan:
            raise PipelineError(
                f"Channel invariant failed for {archive}: expected {expected_nchan}, got {nchan}"
            )
        band_low, band_high = map(float, self.config["subbands"]["full_band_mhz"])
        tolerance = float(self.config["subbands"].get("band_tolerance_mhz", 1.0))
        expected_centre = 0.5 * (band_low + band_high)
        expected_bandwidth = band_high - band_low
        if check_full_band and (
            abs(centre_frequency - expected_centre) > tolerance
            or abs(abs(bandwidth) - expected_bandwidth) > tolerance
        ):
            raise PipelineError(
                f"Configured UWL band {band_low}-{band_high} MHz does not match {archive}: "
                f"freq={centre_frequency}, bw={bandwidth} MHz"
            )
        return {
            "dmc": dmc,
            "nchan": nchan,
            "bandwidth_mhz": bandwidth,
            "centre_frequency_mhz": centre_frequency,
        }

    def _fullband_rows(
        self,
        aligned_cube: dict[tuple[int, int], list[float]],
        mjd: float,
        shift: int,
        correlation: float,
    ) -> list[dict[str, Any]]:
        windows = self.config["phase_windows"]
        thresholds = self.config["thresholds"]
        dual = thresholds["dual_off"]
        state_thresholds = thresholds["fullband_state_snr"]
        rows: list[dict[str, Any]] = []
        channels = {channel for _, channel in aligned_cube}
        if channels != {0}:
            raise PipelineError(
                f"Total-intensity archive must have one channel, found {sorted(channels)}"
            )

        for (subint, _), profile in sorted(aligned_cube.items()):
            mp_primary = measure_window(profile, windows["mp"], windows["off_primary"])
            mp_control = measure_window(profile, windows["mp"], windows["off_control"])
            ip_primary = measure_window(
                profile, windows["ip_test"], windows["off_primary"]
            )
            ip_control = measure_window(
                profile, windows["ip_test"], windows["off_control"]
            )
            off_control_check = measure_window(
                profile, windows["off_control"], windows["off_primary"]
            )
            stability = off_window_stability(
                mp_primary,
                mp_control,
                float(dual["detection_snr"]),
                float(dual["strong_snr"]),
                float(dual["max_snr_delta"]),
            )
            ratio = rms_ratio(mp_primary, mp_control)
            flags: list[str] = []
            if correlation < float(thresholds["template_min_correlation"]):
                flags.append("low_template_correlation")
            if ratio > float(dual["max_rms_ratio"]):
                flags.append("off_rms_mismatch")
            if stability in {
                "invalid",
                "sign_changed",
                "off_window_sensitive_detection",
            }:
                flags.append(stability)
            if abs(off_control_check.snr) > float(dual["off_control_abs_snr_max"]):
                flags.append("off_control_suspicious")

            row: dict[str, Any] = {
                "file": f"{self.obs_id}.I",
                "source_rf": str(self.raw_archive),
                "mjd": f"{mjd:.12f}",
                "subint": subint,
                "template_shift": shift,
                "template_corr": f"{correlation:.12g}",
                "mp_template_window": _window_label(windows["mp"]),
                "ip_test_template_window": _window_label(windows["ip_test"]),
                "off_primary_window": _window_label(windows["off_primary"]),
                "off_control_window": _window_label(windows["off_control"]),
                **mp_primary.as_dict("mp_primary"),
                **mp_control.as_dict("mp_control"),
                **ip_primary.as_dict("ip_primary"),
                **ip_control.as_dict("ip_control"),
                **off_control_check.as_dict("off_control_check"),
                "off_rms_ratio": ratio,
                "off_window_stability": stability,
                "fullband_state": state_from_snr(mp_primary.snr, state_thresholds),
                "qc_pass": str(not flags).lower(),
                "qc_flags": ";".join(flags),
            }
            rows.append(row)
        return rows

    def _subband_rows(
        self,
        aligned_cube: dict[tuple[int, int], list[float]],
        count: int,
        fullband_by_subint: dict[int, dict[str, Any]],
        mjd: float,
        shift: int,
        correlation: float,
        bandwidth_mhz: float,
    ) -> list[dict[str, Any]]:
        windows = self.config["phase_windows"]
        dual = self.config["thresholds"]["dual_off"]
        edges = (
            [float(value) for value in self.config["subbands"]["four_edges_mhz"]]
            if count == 4
            else _expected_edges(self.config["subbands"]["full_band_mhz"], count)
        )
        seen_channels = sorted({channel for _, channel in aligned_cube})
        if seen_channels != list(range(count)):
            raise PipelineError(
                f"Expected dedispersed {count}-band archive channels 0..{count - 1}; got {seen_channels}"
            )
        rows: list[dict[str, Any]] = []
        for (subint, channel), profile in sorted(aligned_cube.items()):
            frequency_index = channel if bandwidth_mhz >= 0 else count - 1 - channel
            mp_primary = measure_window(profile, windows["mp"], windows["off_primary"])
            mp_control = measure_window(profile, windows["mp"], windows["off_control"])
            ip_primary = measure_window(
                profile, windows["ip_test"], windows["off_primary"]
            )
            ip_control = measure_window(
                profile, windows["ip_test"], windows["off_control"]
            )
            stability = off_window_stability(
                mp_primary,
                mp_control,
                float(dual["detection_snr"]),
                float(dual["strong_snr"]),
                float(dual["max_snr_delta"]),
            )
            full = fullband_by_subint[subint]
            rows.append(
                {
                    "file": full["file"],
                    "mjd": f"{mjd:.12f}",
                    "subint": subint,
                    "fullband_state": full["fullband_state"],
                    "fullband_qc_pass": full["qc_pass"],
                    "n_subbands": count,
                    "subband_index": frequency_index,
                    "archive_channel_index": channel,
                    "archive_bandwidth_mhz": bandwidth_mhz,
                    "freq_low_mhz": f"{edges[frequency_index]:.6f}",
                    "freq_high_mhz": f"{edges[frequency_index + 1]:.6f}",
                    "template_shift": shift,
                    "template_corr": f"{correlation:.12g}",
                    **mp_primary.as_dict("mp_primary"),
                    **mp_control.as_dict("mp_control"),
                    **ip_primary.as_dict("ip_primary"),
                    **ip_control.as_dict("ip_control"),
                    "off_rms_ratio": rms_ratio(mp_primary, mp_control),
                    "off_window_stability": stability,
                }
            )
        return rows

    def run(self) -> Path:
        self._prepare()
        if not self.dry_run:
            require_tools()
        template = self._template_path()
        if not self.dry_run and not template.exists():
            raise PipelineError(
                f"Template not found: {template}. Copy the independently chosen FTP template and update the config."
            )

        manifest_path = self.stages["00_manifest"] / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["template"] = {"path": str(template)}
        if template.exists():
            manifest["template"].update(
                {"size_bytes": template.stat().st_size, "sha256": _sha256(template)}
            )
        manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
        self.runner.run(
            ["pam", "--version"],
            capture_path=self.stages["01_checks"] / "psrchive_pam_version.txt",
            allow_failure=True,
        )

        plot_allow_failure = not bool(self.config["archive"]["plot_failures_are_fatal"])
        write_archive_checks(
            self.runner,
            self.raw_archive,
            self.stages["01_checks"],
            f"{self.obs_id}_raw",
        )
        make_plots(
            self.runner,
            self.raw_archive,
            self.stages["02_raw_plots"],
            f"{self.obs_id}_raw",
            allow_failure=plot_allow_failure,
        )

        zap = self.stages["03_zap"] / f"{self.obs_id}.zap"
        if not (self.resume and zap.exists()):
            zap = make_zap(
                self.runner,
                self.raw_archive,
                self.stages["03_zap"],
                list(self.config["archive"]["automatic_zap_args"]),
            )
        write_archive_checks(
            self.runner, zap, self.stages["01_checks"], f"{self.obs_id}_zap"
        )
        make_plots(
            self.runner,
            zap,
            self.stages["04_zap_plots"],
            f"{self.obs_id}_zap",
            allow_failure=plot_allow_failure,
        )

        intensity = self.stages["05_total_intensity"] / f"{self.obs_id}.I"
        if not (self.resume and intensity.exists()):
            intensity = make_total_intensity(
                self.runner, zap, self.stages["05_total_intensity"]
            )
        write_archive_checks(
            self.runner, intensity, self.stages["01_checks"], f"{self.obs_id}_I"
        )
        make_plots(
            self.runner,
            intensity,
            self.stages["05_total_intensity"],
            f"{self.obs_id}_I",
            allow_failure=plot_allow_failure,
        )

        subband_archives: dict[int, Path] = {}
        for count in self.config["subbands"]["counts"]:
            directory = self.stages["09_subbands"] / f"n{count:02d}"
            expected = directory / f"{self.obs_id}.I{count}D"
            if self.resume and expected.exists():
                archive, command = expected, ["resume-existing", str(expected)]
            else:
                archive, command = make_subbands(
                    self.runner, zap, directory, int(count)
                )
            subband_archives[int(count)] = archive
            make_plots(
                self.runner,
                archive,
                directory / "plots",
                f"{self.obs_id}_I{count}D",
                allow_failure=plot_allow_failure,
            )
            _write_json(
                directory / "provenance.json",
                {
                    "source_zap": str(zap),
                    "archive": str(archive),
                    "command": command,
                    "explicit_dedispersion": True,
                    "time_scrunched": False,
                    "raw_channel_pooling": False,
                },
            )

        if self.dry_run:
            _write_json(
                self.stages["00_manifest"] / "status.json",
                {"status": "dry_run_complete", "observation_id": self.obs_id},
            )
            return self.root

        # A one-channel fscrunch may store a zap-weighted centre frequency;
        # the multi-channel products below enforce the nominal full-band gate.
        self._assert_dedispersed(intensity, 1, check_full_band=False)
        subband_metadata: dict[int, dict[str, int | float]] = {}
        for count, archive in subband_archives.items():
            metadata = self._assert_dedispersed(archive, count)
            subband_metadata[count] = metadata
            provenance_path = archive.parent / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance.update(metadata)
            provenance_path.write_text(canonical_json(provenance), encoding="utf-8")

        nbin = int(self.config["archive"]["expected_nbin"])
        intensity_text = dump_profiles(
            self.runner,
            intensity,
            self.stages["06_profiles"] / f"{self.obs_id}_I.pdv.txt",
        )
        template_text = dump_profiles(
            self.runner,
            template,
            self.stages["06_profiles"] / f"{template.stem}.template.pdv.txt",
        )
        intensity_cube = parse_pdv_text(intensity_text, expected_nbin=nbin)
        template_cube = parse_pdv_text(template_text, expected_nbin=nbin)
        observation_average = average_cube(intensity_cube)
        template_average = average_cube(template_cube)
        shift, correlation = best_circular_alignment(
            template_average, observation_average
        )
        aligned_intensity = align_cube(intensity_cube, shift)
        aligned_average = average_cube(aligned_intensity)

        _write_csv(
            self.stages["06_profiles"] / f"{self.obs_id}_average_profile.csv",
            [
                {"bin": index, "intensity": value}
                for index, value in enumerate(observation_average)
            ],
        )
        _write_csv(
            self.stages["07_template_match"]
            / f"{self.obs_id}_aligned_average_profile.csv",
            [
                {"bin": index, "intensity": value}
                for index, value in enumerate(aligned_average)
            ],
        )
        profile_svg(
            aligned_average,
            self.stages["07_template_match"] / f"{self.obs_id}_aligned_profile.svg",
            f"{self.obs_id}: template-aligned average profile",
            {
                name: self.config["phase_windows"][name]
                for name in ("mp", "ip_test", "off_primary", "off_control")
            },
        )
        _write_json(
            self.stages["07_template_match"] / "template_match.json",
            {
                "observation": str(intensity),
                "template": str(template),
                "alignment_definition": "aligned[i] = observation[(i + shift) modulo nbin]",
                "best_shift_bins": shift,
                "best_correlation": correlation,
                "one_shift_for_all_subints_and_subbands": True,
            },
        )

        mjd = query_mjd(self.runner, intensity)
        fullband_rows = self._fullband_rows(aligned_intensity, mjd, shift, correlation)
        _write_csv(self.stages["08_qc"] / "subint_metrics.csv", fullband_rows)
        fullband_by_subint = {int(row["subint"]): row for row in fullband_rows}

        all_subband_rows: dict[int, list[dict[str, Any]]] = {}
        for count, archive in subband_archives.items():
            capture = archive.parent / f"{self.obs_id}_I{count}D.pdv.txt"
            text = dump_profiles(self.runner, archive, capture)
            cube = parse_pdv_text(text, expected_nbin=nbin)
            aligned = align_cube(cube, shift)
            rows = self._subband_rows(
                aligned,
                count,
                fullband_by_subint,
                mjd,
                shift,
                correlation,
                float(subband_metadata[count]["bandwidth_mhz"]),
            )
            all_subband_rows[count] = rows
            _write_csv(archive.parent / "subband_metrics.csv", rows)

        four_by_subint: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in all_subband_rows[4]:
            four_by_subint[int(row["subint"])].append(row)
        candidate_rows: list[dict[str, Any]] = []
        candidate_thresholds = self.config["thresholds"]["candidate"]
        for subint, rows in sorted(four_by_subint.items()):
            classification = classify_four_band_event(rows, candidate_thresholds)
            full = fullband_by_subint[subint]
            if (
                full["fullband_state"] == "bad_or_non_detection"
                and classification["candidate_tier"] != "none"
            ):
                classification["subband_classification"] = "subband_only_suspect"
                classification["candidate_tier"] = "C"
            if full["qc_pass"] != "true" and classification["candidate_tier"] in {
                "A",
                "B",
            }:
                classification["subband_classification"] = (
                    "background_sensitive_candidate"
                )
                classification["candidate_tier"] = "C"
            candidate_rows.append(
                {
                    "file": full["file"],
                    "mjd": full["mjd"],
                    "subint": subint,
                    "fullband_state": full["fullband_state"],
                    "fullband_mp_energy": full["mp_primary_energy"],
                    "fullband_mp_error": full["mp_primary_error"],
                    "fullband_mp_snr": full["mp_primary_snr"],
                    "fullband_qc_pass": full["qc_pass"],
                    "fullband_qc_flags": full["qc_flags"],
                    **classification,
                    "evidence_scope": "candidate_evidence_only",
                }
            )
        _write_csv(
            self.stages["10_candidates"] / "candidate_events.csv", candidate_rows
        )

        annotation = self.config.get("known_event_annotations", {}).get(self.obs_id)
        observation = summarize_observation(candidate_rows, annotation)
        state_counts = Counter(row["fullband_state"] for row in fullband_rows)
        accepted = [row for row in fullband_rows if row["qc_pass"] == "true"]
        energy_rows = accepted or fullband_rows
        observation.update(
            {
                "n_strong": state_counts.get("strong", 0),
                "n_weak": state_counts.get("weak", 0),
                "n_low_snr": state_counts.get("low_snr", 0),
                "n_bad_or_non_detection": state_counts.get("bad_or_non_detection", 0),
                "n_qc_pass": len(accepted),
                "template_corr": f"{correlation:.12g}",
                "mean_mp_energy_primary": sum(
                    float(row["mp_primary_energy"]) for row in energy_rows
                )
                / len(energy_rows),
                "mean_mp_snr_primary": sum(
                    float(row["mp_primary_snr"]) for row in energy_rows
                )
                / len(energy_rows),
                "relative_energy_units": "arbitrary; not mJy",
            }
        )
        _write_csv(
            self.stages["10_candidates"] / "observation_summary.csv", [observation]
        )
        _write_json(
            self.stages["00_manifest"] / "status.json",
            {
                "status": "complete",
                "observation_id": self.obs_id,
                "completed_utc": datetime.now(timezone.utc).isoformat(),
                "template_correlation": correlation,
                "n_subint": len(fullband_rows),
            },
        )
        return self.root


def run_observation(
    config: dict[str, Any],
    raw_archive: str | Path,
    output_root: str | Path,
    *,
    dry_run: bool = False,
    resume: bool = False,
    hash_inputs: bool = False,
) -> Path:
    pipeline = ObservationPipeline(
        config,
        Path(raw_archive),
        Path(output_root),
        dry_run=dry_run,
        resume=resume,
        hash_inputs=hash_inputs,
    )
    try:
        return pipeline.run()
    except Exception as exc:
        if pipeline.stages["00_manifest"].exists():
            _write_json(
                pipeline.stages["00_manifest"] / "status.json",
                {
                    "status": "failed",
                    "observation_id": pipeline.obs_id,
                    "failed_utc": datetime.now(timezone.utc).isoformat(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        if isinstance(exc, PipelineError):
            raise
        if isinstance(exc, (CommandError, ValueError)):
            raise PipelineError(str(exc)) from exc
        raise
