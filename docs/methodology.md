# Methodology and scientific guardrails

## 1. Data products and order of operations

The raw folded `.rf` archive is immutable. `paz -r` writes a separate `.zap` archive. The latter preserves time resolution and polarization information for future calibrated work.

Every product used for a frequency comparison is explicitly dedispersed before frequency channels are combined:

```text
full band: pam -D -F -p
subbands:  pam -D -p --setnchn N
```

The pipeline then queries `dmc`, `nchan`, centre frequency, and signed bandwidth. A subband archive is rejected unless `dmc=1`, `nchan=N`, and its band matches the frozen `704–4032 MHz` range within tolerance. Negative-bandwidth archives are mapped back to low-to-high frequency indices before classification. This guards against the earlier failure mode in which undedispersed channel profiles were pooled directly: their phase coordinates are not interchangeable, and raw-channel sums can create misleading band-dependent energies.

No command contains `-T`; the original subintegrations are retained.

## 2. Template coordinate system

Let `r[i]` be the independently selected template profile and `x[i]` the observation-average total-intensity profile. Both are standardized once over all bins. The pipeline selects the circular shift `s` maximizing

```text
corr(s) = mean_i r[i] x[(i+s) mod nbin].
```

All subsequent profiles use

```text
x_aligned[i] = x[(i+s) mod nbin].
```

The same observation-level `s` is applied to all subintegrations and all 4/8/16-band profiles. Independent per-subint or per-band alignment is forbidden because it would optimize noise and undermine the coherence test.

## 3. Window measurement

Window endpoints use Python's half-open convention `[start,end)` so that `465–525` contains 60 bins and `650–800` contains 150. Wraparound windows such as `[970,30)` are supported. For on-window values `x` and off-window mean `b`, integrated relative energy is

```text
E = sum_on (x - b).
```

With off-pulse sample standard deviation `sigma`, `n_on` on bins and `n_off` off bins, the reported measurement error is

```text
sigma_E = sigma sqrt[n_on (1 + n_on/n_off)].
```

The second term propagates uncertainty in the estimated baseline mean. `S/N = E/sigma_E`.

Every MP and candidate-IP measurement is repeated with `off_primary=650–800` and `off_control=100–250`. The table records sign changes, one-window-only detections, S/N disagreement, off-RMS ratio, and the control-window energy measured against the primary baseline.

The candidate-IP label is deliberate. The current average profile does not by itself establish a physically secure interpulse window.

## 4. QC and state descriptions

Default descriptive full-band labels are:

```text
S/N < 3       bad_or_non_detection
3 <= S/N < 5  low_snr
5 <= S/N < 8  weak
S/N >= 8      strong
```

QC flags come only from predeclared data-quality quantities: template correlation, off-window stability, off-RMS ratio, and control-window contamination. IP behavior never changes QC or the MP grouping.

These labels describe pulse-energy measurements; they are not HMM states.

## 5. Four-band coherence

For each dedispersed four-band profile, a band is robustly positive only when both baseline choices give MP S/N above the frozen band threshold. A stable negative band, sign change, or one-window-only detection blocks a full-UWL claim.

```text
4/4 robust positive                  Tier A / full-UWL coherent candidate
3/4 robust positive, no negative     Tier B / likely broadband candidate
1–2 adjacent robust positive         Tier C / frequency-selective candidate
only highest-frequency band          Tier C / high-frequency-limited candidate
sign conflict or stable negative     Tier C / no coherent broadband response
off-window sensitivity               Tier C / background-sensitive candidate
```

A subband-only feature without a full-band detection is kept as a suspect, not promoted.

The 8- and 16-band products refine frequency localization and RFI review. They do not replace the predeclared four-band primary test.

## 6. External classifier and small-sample boundary

`reference_band_index` must first be selected using only data-quality measures such as valid data fraction and off-pulse RMS. For a target observation, all its rows are excluded from training. The feature is reference-band MP S/N, not raw energy pooled across observing sessions.

The optional classifier compares one Gaussian with a two-component Gaussian mixture using BIC and a frozen component-separation threshold. It refuses to emit frozen probabilities unless the model checks pass. A hard label is only a plotting aid:

```text
p_high >= 0.8  MP-high
p_high <= 0.2  MP-low
otherwise      uncertain
```

No single-file median split is permitted. For approximately seven time samples, no HMM, dwell-time, transition-rate, circular-shift significance, or lag fit is reported.

## 7. Conditional candidate-IP analysis

When externally trained probabilities have been frozen, the optional descriptive statistic in band `b` is

```text
Delta_IP,b = sum(p E/sigma^2)/sum(p/sigma^2)
           - sum((1-p) E/sigma^2)/sum((1-p)/sigma^2).
```

The fixed-probability regression is

```text
E_IP,t,b = alpha_b + beta_b p_t + error.
```

A common-gain control additionally includes reference-band MP energy. The script reports coefficients and measurement-model errors, not asymptotic significance. A valid four-band joint test must derive the covariance matrix from many predeclared off-pulse pseudo-windows or covariance-preserving noise simulations, not from seven residuals.

## 8. Interpretation boundary

Outputs support statements about candidate radiative counterparts to timing-state behavior. Without absolute flux calibration, full-Stokes calibration, and adequate time resolution, they do not independently demonstrate intrinsic radiative mode changing, polarization-state switching, dwell times, or transition delays.
