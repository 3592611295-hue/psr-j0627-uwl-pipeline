from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bref import ReferenceBandError, build_reference_band_qc_report
from .classifier import ClassifierError, freeze_target_groups
from .conditional import ConditionalError, run_conditional_ip
from .config import ConfigError, config_hash, load_config, public_config
from .pipeline import PipelineError, run_observation
from .summary import SummaryError, build_master_summary


def _common_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="Frozen JSON configuration")
    parser.add_argument("--output", required=True, help="Results root")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing archives under the same frozen config",
    )
    parser.add_argument(
        "--hash-inputs",
        action="store_true",
        help="SHA-256 raw .rf files (slower but stronger provenance)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="j0627-uwl",
        description="Parkes/UWL PSRCHIVE pipeline for PSR J0627+0706",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate-config", help="Validate and fingerprint a configuration"
    )
    validate.add_argument("--config", required=True)

    plan = subparsers.add_parser(
        "plan", help="Print and log the PSRCHIVE command plan without running it"
    )
    _common_run_arguments(plan)
    plan.add_argument("--input", required=True, help="One .rf archive")

    run = subparsers.add_parser("run", help="Process one .rf archive")
    _common_run_arguments(run)
    run.add_argument("--input", required=True, help="One .rf archive")

    batch = subparsers.add_parser(
        "batch", help="Process all matching .rf archives sequentially"
    )
    _common_run_arguments(batch)
    batch.add_argument("--input-dir", required=True)
    batch.add_argument("--pattern", default="*.rf")

    summarize = subparsers.add_parser(
        "summarize", help="Build de-duplicated master tables and MJD plot"
    )
    summarize.add_argument("--results", required=True)

    bref = subparsers.add_parser(
        "bref-report",
        help="Build a four-band QC-only report to support manual B_ref freezing",
    )
    bref.add_argument("--results", required=True)

    freeze = subparsers.add_parser(
        "freeze-groups",
        help="Fit a leave-target-out external MP classifier and freeze probabilities for one observation",
    )
    freeze.add_argument("--config", required=True)
    freeze.add_argument("--results", required=True)
    freeze.add_argument(
        "--target", required=True, help="Observation basename, .rf name, or .I name"
    )
    freeze.add_argument(
        "--replace-frozen",
        action="store_true",
        help="Explicitly replace existing frozen files; normally forbidden",
    )

    conditional = subparsers.add_parser(
        "conditional-ip",
        help="Run weighted IP differences and fixed-probability regressions from frozen MP probabilities",
    )
    conditional.add_argument("--config", required=True)
    conditional.add_argument("--results", required=True)
    conditional.add_argument("--target", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            config = load_config(args.config)
            print("valid config_sha256=" + config_hash(public_config(config)))
            return 0
        if args.command in {"plan", "run"}:
            config = load_config(args.config)
            result = run_observation(
                config,
                args.input,
                args.output,
                dry_run=args.command == "plan",
                resume=args.resume,
                hash_inputs=args.hash_inputs,
            )
            print("output:", result)
            if args.command == "run":
                print("master summary:", build_master_summary(args.output))
            return 0
        if args.command == "batch":
            config = load_config(args.config)
            inputs = sorted(
                Path(args.input_dir).expanduser().resolve().glob(args.pattern)
            )
            if not inputs:
                raise PipelineError(
                    f"No inputs match {args.pattern!r} under {args.input_dir}"
                )
            failures: list[tuple[Path, str]] = []
            for archive in inputs:
                try:
                    print(f"\n=== {archive.name} ===")
                    run_observation(
                        config,
                        archive,
                        args.output,
                        resume=args.resume,
                        hash_inputs=args.hash_inputs,
                    )
                except PipelineError as exc:
                    failures.append((archive, str(exc)))
                    print(f"FAILED {archive}: {exc}", file=sys.stderr)
            if failures:
                if len(failures) < len(inputs):
                    print("partial master summary:", build_master_summary(args.output))
                print(
                    f"{len(failures)} observation(s) failed; successful observations were preserved",
                    file=sys.stderr,
                )
                return 2
            print("output:", Path(args.output).expanduser().resolve())
            print("master summary:", build_master_summary(args.output))
            return 0
        if args.command == "summarize":
            print("output:", build_master_summary(args.results))
            return 0
        if args.command == "bref-report":
            print("output:", build_reference_band_qc_report(args.results))
            return 0
        if args.command == "freeze-groups":
            config = load_config(args.config)
            print(
                "output:",
                freeze_target_groups(
                    args.results,
                    args.target,
                    config,
                    replace=args.replace_frozen,
                ),
            )
            return 0
        if args.command == "conditional-ip":
            config = load_config(args.config)
            print("output:", run_conditional_ip(args.results, args.target, config))
            return 0
    except (
        ConfigError,
        PipelineError,
        SummaryError,
        ClassifierError,
        ConditionalError,
        ReferenceBandError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
