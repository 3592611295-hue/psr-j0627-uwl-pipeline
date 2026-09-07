#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 CONFIG_JSON INPUT_RF RESULTS_ROOT [additional j0627-uwl options]" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "${script_dir}/.." && pwd)"
config_path="$1"
input_path="$2"
results_root="$3"
shift 3

export PYTHONPATH="${repo_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec python3 -m j0627_uwl run \
  --config "${config_path}" \
  --input "${input_path}" \
  --output "${results_root}" \
  "$@"
