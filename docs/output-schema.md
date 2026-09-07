# Output schema

All CSV files contain exactly one header. Duplicate `(file, subint)` keys cause master-summary generation to fail rather than being silently retained.

## `08_qc/subint_metrics.csv`

One row per original subintegration.

- `file`, `source_rf`, `mjd`, `subint`: identity and epoch.
- `template_shift`, `template_corr`: the single observation-level alignment.
- `*_template_window`: frozen Python half-open `[start,end)` bin windows.
- `mp_primary_*`, `mp_control_*`: MP energy, propagated error, S/N, baseline mean/RMS and bin counts for each off choice.
- `ip_primary_*`, `ip_control_*`: the same for the candidate-IP test window.
- `off_control_check_*`: control window measured as a pseudo-on window against the primary off baseline.
- `off_rms_ratio`, `off_window_stability`: dual-off diagnostics.
- `fullband_state`: descriptive S/N bin.
- `qc_pass`, `qc_flags`: data-quality decision independent of IP behavior.

## `09_subbands/nNN/subband_metrics.csv`

One row per `(subint, subband)` from an explicitly dedispersed PSRCHIVE archive.

- `n_subbands`, `subband_index`, `freq_low_mhz`, `freq_high_mhz`: low-to-high-frequency subband identity.
- `archive_channel_index`, `archive_bandwidth_mhz`: original PSRCHIVE channel order; negative-bandwidth archives are remapped before a band is called "high frequency".
- `fullband_state`, `fullband_qc_pass`: frozen fullband context.
- `mp_*`, `ip_*`, `off_*`: dual-off measurements in the common template coordinate system.

`provenance.json` records the exact `pam -D ... --setnchn N` command, `dmc`, `nchan`, and the prohibition on raw-channel pooling.

## `10_candidates/candidate_events.csv`

One row per subintegration. Primary candidate classification uses only `n04/subband_metrics.csv`.

- `subband_classification`: coherence/background/frequency-selective label.
- `candidate_tier`: `A`, `B`, `C`, or `none`.
- `n_robust_positive_bands`, `n_robust_negative_bands`, `n_sensitive_bands`.
- `positive_band_indices`, `band_states`: auditable four-band decision inputs.
- `evidence_scope`: always `candidate_evidence_only` in this release.

## `10_candidates/observation_summary.csv`

One row per `.rf` file, including state counts, candidate counts, template correlation, accepted-QC count, mean relative MP energy, analysis role, and broadband-pool eligibility.

Known high-frequency-limited review files remain visibly annotated and excluded from the broadband pool unless the frozen configuration is intentionally revised in a new result tree.

## Optional frozen-state files

- `external_mp_classifier.json`: target-excluded mixture parameters and model checks.
- `external_classifier_training_files.csv`: exact leave-target-out training observation list.
- `external_classifier_checksums.txt`: SHA-256 hashes of training metric tables.
- `mp_groups_frozen.csv`: continuous probabilities and plotting-only hard labels.
- `conditional_ip_results.csv`: probability-weighted IP differences and fixed-probability/common-gain regressions without asymptotic p-values.
