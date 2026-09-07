from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


class CommandError(RuntimeError):
    """Raised when an external PSRCHIVE command fails."""


REQUIRED_TOOLS = ("vap", "psrstat", "psrplot", "paz", "pam", "psredit", "pdv")


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, log_path: Path, dry_run: bool = False):
        self.log_path = log_path
        self.dry_run = dry_run

    def _log(self, payload: dict[str, object]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def run(
        self,
        args: Sequence[str | Path],
        *,
        cwd: Path | None = None,
        capture_path: Path | None = None,
        allow_failure: bool = False,
    ) -> CommandResult:
        command = [str(arg) for arg in args]
        started = datetime.now(timezone.utc).isoformat()
        print("$", shlex.join(command))
        if self.dry_run:
            result = CommandResult(command, 0, "", "")
            self._log(
                {
                    "time_utc": started,
                    "dry_run": True,
                    "cwd": str(cwd) if cwd else None,
                    "command": command,
                }
            )
            return result

        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
        )
        result = CommandResult(
            command, completed.returncode, completed.stdout, completed.stderr
        )
        if capture_path is not None:
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            capture_path.write_text(completed.stdout, encoding="utf-8")
            if completed.stderr:
                capture_path.with_suffix(
                    capture_path.suffix + ".stderr.txt"
                ).write_text(completed.stderr, encoding="utf-8")
        self._log(
            {
                "time_utc": started,
                "dry_run": False,
                "cwd": str(cwd) if cwd else None,
                "command": command,
                "returncode": completed.returncode,
                "stdout_tail": completed.stdout[-4000:],
                "stderr_tail": completed.stderr[-4000:],
            }
        )
        if completed.returncode != 0 and not allow_failure:
            raise CommandError(
                f"Command failed ({completed.returncode}): {shlex.join(command)}\n{completed.stderr.strip()}"
            )
        return result


def require_tools() -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    if missing:
        raise CommandError(
            "Missing PSRCHIVE commands: "
            + ", ".join(missing)
            + ". Run inside the documented container."
        )


def expected_archive(source: Path, output_dir: Path, extension: str) -> Path:
    return output_dir / f"{source.stem}.{extension}"


def write_archive_checks(
    runner: CommandRunner, archive: Path, output_dir: Path, label: str
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    runner.run(["vap", archive], capture_path=output_dir / f"{label}_vap.txt")
    runner.run(["psrstat", archive], capture_path=output_dir / f"{label}_psrstat.txt")
    runner.run(
        [
            "vap",
            "-c",
            "file,src,nbin,nsub,nchan,npol,freq,bw,dm,rm",
            archive,
        ],
        capture_path=output_dir / f"{label}_vap_table.txt",
    )
    runner.run(
        ["psredit", "-qc", "dm,dmc", archive],
        capture_path=output_dir / f"{label}_psredit.txt",
    )


def make_plots(
    runner: CommandRunner,
    archive: Path,
    output_dir: Path,
    label: str,
    *,
    allow_failure: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for plot_type in ("flux", "freq"):
        output = output_dir / f"{label}_{plot_type}.gif"
        runner.run(
            ["psrplot", "-p", plot_type, archive, "-D", f"{output}/gif"],
            allow_failure=allow_failure,
        )


def make_zap(
    runner: CommandRunner,
    raw_archive: Path,
    output_dir: Path,
    paz_args: list[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = expected_archive(raw_archive, output_dir, "zap")
    runner.run(["paz", *paz_args, "-O", output_dir, "-e", "zap", raw_archive])
    if not runner.dry_run and not output.exists():
        raise CommandError(f"paz completed but expected output was not found: {output}")
    return output


def make_total_intensity(
    runner: CommandRunner,
    zap_archive: Path,
    output_dir: Path,
) -> Path:
    """Explicitly dedisperse, frequency-scrunch, and polarization-scrunch.

    The order is recorded in provenance. No time-scrunch option is ever used.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output = expected_archive(zap_archive, output_dir, "I")
    runner.run(["pam", "-D", "-F", "-p", "-u", output_dir, "-e", "I", zap_archive])
    if not runner.dry_run and not output.exists():
        raise CommandError(f"pam completed but expected output was not found: {output}")
    return output


def make_subbands(
    runner: CommandRunner,
    zap_archive: Path,
    output_dir: Path,
    count: int,
) -> tuple[Path, list[str]]:
    """Create PSRCHIVE-weighted subbands after explicit dedispersion.

    Python code must not emulate this by summing raw-channel ``pdv`` rows.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    extension = f"I{count}D"
    output = expected_archive(zap_archive, output_dir, extension)
    command = [
        "pam",
        "-D",
        "-p",
        "--setnchn",
        str(count),
        "-u",
        str(output_dir),
        "-e",
        extension,
        str(zap_archive),
    ]
    runner.run(command)
    if not runner.dry_run and not output.exists():
        raise CommandError(f"pam completed but expected output was not found: {output}")
    return output, command


def query_psredit(runner: CommandRunner, archive: Path, expression: str) -> str:
    result = runner.run(["psredit", "-Qqc", expression, archive])
    return result.stdout.strip()


def query_mjd(runner: CommandRunner, archive: Path) -> float:
    output = query_psredit(runner, archive, "int[0]:mjd%30")
    for token in reversed(output.replace("=", " ").split()):
        try:
            value = float(token)
        except ValueError:
            continue
        if 30000.0 < value < 100000.0:
            return value
    raise CommandError(f"Could not parse MJD from psredit output: {output!r}")


def query_integer(runner: CommandRunner, archive: Path, expression: str) -> int:
    output = query_psredit(runner, archive, expression)
    for token in reversed(output.replace("=", " ").split()):
        try:
            return int(round(float(token)))
        except ValueError:
            continue
    raise CommandError(f"Could not parse {expression} from psredit output: {output!r}")


def query_float(runner: CommandRunner, archive: Path, expression: str) -> float:
    output = query_psredit(runner, archive, expression)
    for token in reversed(output.replace("=", " ").split()):
        try:
            return float(token)
        except ValueError:
            continue
    raise CommandError(f"Could not parse {expression} from psredit output: {output!r}")


def dump_profiles(runner: CommandRunner, archive: Path, capture_path: Path) -> str:
    result = runner.run(["pdv", "-t", archive], capture_path=capture_path)
    return result.stdout
