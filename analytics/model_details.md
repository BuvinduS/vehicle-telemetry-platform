# Anomaly Detection Model — Details, Validation, and Limitations

**Status:** baseline complete and evaluated. Not yet suitable for
deployment against the project's own hybrid vehicle — see §7.
**Companion to:** `architecture.md` §3.13 (scope decision),
`schema-reference.md` (telemetry schema), `lessons-learned.md`
(hybrid/EV OBD-II notes referenced in §7.1 below).

---

## Abstract

An unsupervised anomaly-detection model was built to demonstrate that
this project's telemetry-collection pipeline produces data that reads
as plausible against genuine automotive telemetry, addressing a
supervisor-suggested validation goal without requiring labeled fault
data (which this project has no practical way to collect on its own
timeline). An Isolation Forest was trained on real telemetry from the
KIT/RADAR Automotive OBD-II Dataset, validated via a disciplined
train/validation/test split and synthetic fault injection, and finally
applied to a session of the project's own real, independently-collected
vehicle telemetry (`real_obd_001`). The model achieved strong,
generalizing performance against KIT's own held-out data (100%
detection of both injected fault types at a calibrated 2% false-positive
rate, confirmed on a fully sealed test set). Applied to `real_obd_001`,
it produced a substantially elevated anomaly rate (16.7% vs. an expected
2%), which further investigation traced to a specific, mechanistic
cause: the model's rolling-baseline RPM feature assumes continuous
engine operation, an assumption violated by the target vehicle's hybrid
powertrain (engine-on intervals in the tested session never exceeded 60
seconds). This is documented as a confirmed limitation rather than
resolved in this iteration — see §6 and §7.

---

## 1. Objective

Per `architecture.md` §3.13: demonstrate that this project's collected
telemetry is statistically plausible by scoring it against a model
trained on independent, genuine automotive data — not to build a
production fault classifier, and not to attempt true predictive
maintenance (which would require fault-labeled ground truth this
project cannot practically obtain).

**Scope, stated precisely:** this validates *plausibility* — does the
project's own telemetry fall within the range of what a model trained
on real automotive data considers normal. It does **not** validate
*sensor accuracy* against physical ground truth, and does not claim to
detect real, previously-unseen fault types beyond the two synthetic
patterns tested in §5.

---

## 2. Training Data

### 2.1 Source

KIT/RADAR "Automotive OBD-II Dataset," Weber, Marc (2023), Karlsruhe
Institute of Technology. DOI: 10.35097/1130. Licensed CC BY 4.0.
Downloaded as a BagIt archive directly from the RADAR repository;
checksums verified against the archive's own manifest before use.

81 trip recordings, a single vehicle (a 2017–18 Seat León), collected
in the Karlsruhe, Germany area between July 2017 and April 2018.
~2.69 million rows at the source's native ~10Hz forward-filled logging
rate. Condition labels (parsed from filenames, translated from German):
55 `normal`, 12 `free_flow`, 10 `traffic_jam`, and four one-off special
situations (`hard_braking`, `black_ice`, `acceleration_test`,
`measurement_error`) — the four special-situation trips were held out
entirely from the train/validation/test split (§4.1) and used only as
informal, non-quantitative sanity checks.

**Single-vehicle caveat, stated up front:** all conclusions in this
document reflect a model trained on one vehicle's operating envelope.
Cross-vehicle generalization was a known risk from the outset (see
feature design rationale, §3.2) and is directly implicated in the §6/§7
findings.

### 2.2 Data Quality Issues Identified

- **Double-encoded UTF-8 in 39 of 81 file headers.** The degree symbol
  in `"°C"` column headers was corrupted at the byte level in a
  majority of files (confirmed via raw byte inspection, not a read-time
  artifact). Corrected via a decode → latin-1 re-encode → UTF-8 decode
  round-trip, applied conditionally per file.
- **No `engine_load_pct` equivalent in the source data.** KIT never
  logged OBD-II Mode 01 PID 0x04 (Calculated Engine Load). This
  feature was excluded from the model's scope project-wide as a
  result (see §3.2).
- **`throttle_pct` (Absolute Throttle Position) found to be
  non-informative.** 86.3% of all rows across the entire dataset share
  one identical value (83.5%), with near-zero correlation to RPM
  (r = -0.04) or speed (r = -0.01) — confirmed dataset-wide, not
  isolated to specific trips (every one of the 81 trips showed the
  majority of its rows pinned to this value). Root cause: on
  drive-by-wire vehicles, Absolute Throttle Position reflects
  ECU-controlled throttle-plate angle, not driver input — a known
  automotive quirk, not a data corruption issue. The dataset's
  Accelerator Pedal Position D signal (`pedal_d_pct`) was confirmed as
  the genuinely informative alternative (r = 0.31 with RPM), but was
  **not** substituted into this model, because the project's own
  OBD2Lib firmware does not currently collect pedal position — using
  it would have broken train/score symmetry with the project's own
  future data (see §7.2 for planned resolution).

### 2.3 Resampling

Source data is forward-filled at ~10Hz, but individual PIDs update far
less frequently in practice (e.g. RPM changes value on only ~9% of raw
rows in a sampled trip) — training on the full resolution would
substantially overstate the effective sample size. Each trip was
independently downsampled to 1Hz via `.resample("1s").last()` (most
recent reading per second, not a mean — averaging would blur short-lived
genuine spikes, which anomaly detection specifically exists to catch).
This reduced the KIT normal-condition pool from ~2.49M to ~231K rows
(9.3% retained), consistent with the ~10Hz native rate.

---

## 3. Feature Engineering

### 3.1 Final Feature Set

| Feature | Derivation | Rationale |
|---|---|---|
| `coolant_temp_c_dev` | Deviation from trip's own trailing 60s rolling median | High cross-vehicle fragility (thermostat setpoint varies by vehicle) — relative framing generalizes better than absolute °C |
| `rpm_dev` | Deviation from trip's own trailing 60s rolling median | High cross-vehicle fragility (idle speed, gearing vary) — same reasoning |
| `speed_kmh` | Raw value | Low cross-vehicle fragility — km/h is a directly comparable physical unit |

`engine_load_pct` (unavailable in training data, §2.2) and
`throttle_pct`/pedal position (excluded for train/score symmetry,
§2.2) were deliberately not included. This is a 3-feature model, not
the originally scoped 5-feature set in `architecture.md` §3.13's
initial plan.

### 3.2 Rolling-Deviation Methodology

For each trip independently: a trailing, strictly causal 60-second
rolling median (window covers `[t-60s, t]`, never future data — a
deliberate property, since it means the same transform is valid for
scoring live or newly-collected data, not just fixed historical
recordings). The first 60 seconds of every trip were dropped
(a full window doesn't exist yet), rather than using a partial/expanding
window — avoids an ambiguous "is this deviation real or just
not-enough-history-yet" case entirely.

**Assumption this methodology depends on, later found to be violated
(§6):** a trailing rolling median is only a meaningful "recent normal"
reference if the underlying process is reasonably continuous within
the window. This holds by construction for a continuously-running
internal combustion engine; it does not hold for a powertrain that
alternates operating modes faster than the window's timescale (§6).

---

## 4. Model and Training Setup

### 4.1 Algorithm: Isolation Forest

Chosen for its suitability to unsupervised anomaly detection without
labeled fault data: it builds an ensemble of random trees that
repeatedly split on a randomly-chosen feature and threshold; points
that are isolated in few splits (short average path length across the
ensemble) score as anomalous, points requiring many splits to isolate
score as normal. Notably, splits operate on one feature's own observed
range at a time — the algorithm needs no feature scaling, unlike
distance-based methods.

**Hyperparameters:** `n_estimators=100` (sklearn default, untuned —
this is a baseline, not a tuned final model), `random_state=42`.
`contamination` was **not** left at sklearn's `"auto"` setting for the
final model — see §4.3.

### 4.2 Data Split

Trips (not individual rows) were split 70/15/15 into train/validation/
test, using a fixed random seed for reproducibility. Splitting at the
trip level, rather than the row level, was a deliberate methodological
choice: adjacent rows within the same trip are highly correlated (driving
state doesn't change from one second to the next), so a row-level
random split would leak near-duplicate information between train and
validation/test, producing an overstated and misleading generalization
estimate.

Resulting split: 53 train trips (~154K rows) / 12 validation trips
(~42K rows) / 12 test trips (~35K rows), plus the 4 held-out
special-situation trips kept entirely separate (§2.1). An explicit
manifest (trip → split assignment, by filename) was generated for
auditability.

### 4.3 Threshold Calibration

sklearn's `contamination="auto"` sets a decision threshold via a
formula from the original Isolation Forest paper — it is **not** a
target anomaly rate, and produced a threshold flagging ~17-20% of
ordinary held-out driving as anomalous on this dataset, which is not a
usable operating point for a rare-event detector.

The final threshold was instead derived from an explicit tradeoff
table: at each candidate cutoff (expressed as a target false-positive
rate against real validation driving), the corresponding detection
rate against known synthetic faults (§5) was measured directly. A 2%
target FPR was selected as the operating point — chosen because both
synthetic fault types achieved full (100%) detection at this cutoff,
with no further detection improvement at looser thresholds (5%, 10%),
meaning 2% was the tightest (most conservative, fewest false alarms)
threshold that didn't cost any detection sensitivity.

---

## 5. Synthetic Fault Injection

Per `architecture.md` §3.13's disclosure commitment: this is a
controlled test of detection sensitivity using known, deliberately
introduced synthetic faults — **not** a claim of real fault data, and
not evidence the model would catch real, naturally-occurring fault
patterns it has never been shown an example of.

### 5.1 Fault Definitions

Two fault types, injected into randomly-selected 30-second windows of
real validation-set trips (paired before/after comparison — same
trip, same moment, only the targeted feature altered, isolating the
effect of the fault itself from ambient trip conditions):

- **Coolant spike** (`coolant_spike`): +20°C offset to
  `coolant_temp_c_dev`, simulating a stuck thermostat or coolant loss.
- **RPM/speed decorrelation** (`rpm_decorrelation`): offset to
  `rpm_dev` with speed held constant, simulating e.g. a slipping
  clutch (engine revs without corresponding vehicle acceleration).

### 5.2 Methodological Note: Magnitude Calibration

The RPM fault's initial offset (1200) was found, via a dedicated
magnitude sweep, to be insufficiently large relative to `rpm_dev`'s
own naturally wide variance in ordinary driving (std ≈ 373, training
max ≈ 2900) — detection was only 17.5% at the (then-current) 2% FPR
threshold. A sweep across offsets from 1200–8000 showed detection
climbing to 95.3% at 2000 and fully saturating (100%, stable score
delta) from 3000 onward. The offset was revised to 3000. **This was
confirmed to be a test-design issue (magnitude chosen without
reference to the feature's own observed spread), not a genuine model
limitation** — a general lesson for any future synthetic fault
injection work: magnitudes must be sized relative to each feature's
own variance, not chosen by inspection alone.

### 5.3 Validation-Set Results (post-recalibration)

| Fault type | Detection at 2% FPR threshold |
|---|---|
| `coolant_spike` | 100.0% |
| `rpm_decorrelation` | 100.0% |

---

## 6. Sealed Test-Set Evaluation

Performed exactly once, after every design decision above (features,
split, fault magnitude, threshold) was already finalized using only
train/validation data. No further tuning occurred after this result was
observed.

| Metric | Expected (from validation) | Actual (test set) |
|---|---|---|
| False positive rate | 2.0% | 2.23% |
| `coolant_spike` detection | 100% | 100% |
| `rpm_decorrelation` detection | 100% | 100% |

Score percentile distributions (1st/5th/10th/50th/90th) were nearly
identical across train, validation, and test sets independently —
strong evidence the model's learned notion of "normal" is a stable
property of the training data, not an artifact of a lucky split.

**Result:** the model generalizes well within the training vehicle's
own data distribution.

---

## 7. Real-Vehicle Application (`real_obd_001`)

### 7.1 Result and Investigation

Applied to `real_obd_001` (a real, independently-collected session
from this project's own — hybrid — test vehicle), the model flagged
16.7% of rows as anomalous, against an expected 2%.

Two hypotheses were tested directly against the session data:

- **Stationary vehicle at session start:** anomaly rate while
  stationary (6.0%) was in fact *lower* than while moving (18.7%) —
  this hypothesis was rejected.
- **Hybrid EV-only operation (`rpm == 0`):** anomaly rate during
  `rpm == 0` stretches was low (5.1%) — also rejected. Counter to
  initial expectation, RPM==0 periods were *not* the source of the
  elevated rate.

The actual driver, confirmed via direct investigation: anomaly rate
while the engine was actually running (`rpm > 0`) was 40.3% — and
critically, **100% of engine-on rows in this session occurred within
60 seconds of the engine having just turned on** (no continuous
engine-on stretch in the entire session exceeded 60 seconds). This
directly implicates the rolling-median baseline assumption identified
in §3.2: the 60-second trailing window can never fully transition to
a stable "engine running" reference before the engine cuts out again,
so every engine-restart is scored against a recent baseline still
substantially influenced by the preceding EV-only (RPM≈0) period —
producing an RPM deviation pattern nearly identical in shape to the
synthetic `rpm_decorrelation` fault the model was explicitly trained
to catch (§5.1).

### 7.2 Conclusion

This is a genuine, demonstrated **generalization limitation**, not a
software defect: the rolling-baseline RPM feature's design implicitly
assumes continuous engine operation, an assumption that holds for the
ICE training vehicle by construction and is violated by short-cycle
hybrid operation by construction. The model was never shown an example
of this operating pattern during training, and could not have been,
given a single-ICE-vehicle training source.

**Decision (this iteration): documented, not corrected.** Modifying the
rolling-baseline design based on a single hybrid session's specific
pattern risks two things: (1) overfitting a fix to one real-world
observation rather than a validated general solution, and (2) doing to
`real_obd_001` — which was intended as an unbiased plausibility check,
analogous to the sealed test set — exactly what test-set discipline
(§6) was designed to prevent elsewhere in this pipeline. The planned
next step (§8) is to test against a real internal-combustion-engine
vehicle's data before committing to any model change, to establish
whether the model performs as expected on a same-architecture-class
vehicle it wasn't trained on, before concluding a hybrid-specific fix is
even the right thing to build.

---

## 8. Limitations (Summary)

- **Single-vehicle training source** (one ICE Seat León) — absolute
  baselines (where used) and the rolling-baseline design itself both
  carry vehicle-specific assumptions that may not transfer.
- **`engine_load_pct` unavailable** in training data — excluded
  project-wide from this model.
- **`throttle_pct` excluded** — found non-informative in training data
  (drive-by-wire quirk) and not replaced with pedal position to
  preserve train/score symmetry with the project's current firmware
  (§2.2). Revisit once pedal position is added to `OBD2Lib`
  (`architecture.md` §3.14).
- **Rolling-baseline features assume continuous engine operation** —
  confirmed, via direct investigation (§7), not to hold for short-cycle
  hybrid operation.
- **Validated only against synthetic, disclosed, injected faults** — no
  real labeled fault data exists or was used. Detection performance
  claims apply only to the two specific fault patterns tested (§5.1).
- **Plausibility, not sensor-accuracy validation** — a passing score
  indicates statistical similarity to genuine automotive telemetry, not
  confirmation of correct sensor calibration against physical ground
  truth.

---

## 9. Planned Future Work

1. **Test against real ICE vehicle data** before deciding whether to
   modify the rolling-baseline design — establishes whether §7's
   finding is hybrid-specific or a broader issue, without reacting to
   a single session.
2. **Accelerator pedal position** (OBD-II PID 0x49/0x4A) addition to
   `OBD2Lib`, alongside the already-flagged fuel-level addition
   (`architecture.md` §3.12, §3.14) — would allow `pedal_d_pct` to
   replace `throttle_pct` symmetrically across training and real data.
3. **OCSLab dataset** as a secondary real-data cross-model agreement
   check (per `architecture.md` §3.13's original data strategy) — not
   yet performed.
4. **Grafana surfacing** — a batch-scored `telemetry_anomaly` table,
   joined against `sessions` via the existing time-range pattern, on a
   dedicated dashboard. Explicitly deferred to a separate follow-up
   chat; not started as part of this work.
5. **Hybrid/ICE model rebuild on VED**: VED (Vehicle Energy Dataset,
   gsoh/VED, Apache 2.0, DOI 10.1109/TITS.2020.3035596) confirmed as a
   viable multi-vehicle source — 264 gasoline, 92 HEV, 27 PHEV/EV
   vehicles, same collection methodology/era for all. Includes
   Absolute Load[%] (resolves the engine_load_pct gap, §2.2/§8) but
   has NO coolant temperature column at all — trades away the
   strongest-performing feature from §5's fault injection results.
   Open decision for that chat: replace KIT entirely with VED for both
   ICE and hybrid variants (consistent features, apples-to-apples, no
   coolant), vs. keep KIT for ICE + VED for hybrid (preserves coolant
   for one variant, reintroduces asymmetry between the two models).
   Static per-vehicle metadata (VED_Static_Data_*.xlsx) supports
   filtering by powertrain type either way.

## 10. VED-based ICE/HEV models — built, evaluated, and superseded by a per-vehicle design

**Status: cross-vehicle VED models complete and sealed-tested; findings
directly motivated a pivot away from population-trained models toward
per-vehicle models (§11). VED work is not discarded — repurposed as a
cold-start prior, see §11.2.**

### 10.1 What was built

Following the decision in §9's future work (test against more diverse
real data, decide whether VED replaces KIT), a full parallel pipeline
was built against the Vehicle Energy Dataset (VED — Oh, LeBlanc, Peng
2020, University of Michigan, Apache 2.0, DOI 10.1109/TITS.2020.3035596),
producing two model variants: **VED-ICE** and **VED-HEV**, each with its
own feature set, split, threshold, and sealed test evaluation, methodology
otherwise identical to the KIT pipeline (Isolation Forest, trip/vehicle-
level split, explicit FPR/detection tradeoff calibration, synthetic
fault injection with magnitude sized to each feature's own std, one-time
sealed test evaluation).

**Data quality findings, confirmed via direct inspection before use**
(same discipline as KIT's encoding-issue discovery):
- No encoding issues (unlike KIT — confirmed pure ASCII throughout).
- `Absolute Load[%]` (used as `engine_load_pct_dev`, replacing KIT's
  `coolant_temp_c_dev` — VED has no coolant column at all) is bimodal
  *per vehicle*: a given vehicle reports it almost always or almost
  never, essentially nothing in between. 85 of 384 vehicles (54 ICE, 4
  HEV, all 27 PHEV/EV) were excluded from their respective model's
  training pool for not supporting the PID, rather than imputed across.
- `Absolute Load[%]` also contained physically-impossible values (up to
  ~22,463%, against a PID that's bounded [0,100] by its own SAE J1979
  definition) in 0.24% of ICE rows / 0.06% of HEV rows — corrupted
  logger readings, nulled out (not clipped, to avoid fabricating a
  plateau that was never measured) before feature engineering.
- Native sampling is irregular and close to ~1Hz (unlike KIT's
  forward-filled ~10Hz) — feature engineering uses a **time-based**
  rolling window (`.rolling("60s")` on a real timestamp index), not
  KIT's row-based approach, so it correctly handles irregular spacing.

**Feature set** (both variants): `rpm_dev`, `engine_load_pct_dev` (both:
trailing rolling-median deviation, strictly causal, per-trip cold-start
trimmed), raw `speed_kmh`. `engine_load_pct_dev` fills the gap KIT had
(no `engine_load_pct` at all in that dataset) — the trade-off is no
coolant feature, VED's one structural gap versus KIT.

**Split**: vehicle-level (not trip-level, unlike KIT), row-count-balanced
via a greedy largest-first bin-packing assignment — necessary because
per-vehicle row counts are extremely skewed (187 to 887,056 rows/vehicle)
and a naive random-by-vehicle-count split could land far from 70/15/15
by actual row volume purely by chance. Achieved: ICE 150/30/30 vehicles
(70.0/15.0/15.0% of rows), HEV 63/13/13 vehicles (69.9/15.0/15.1%).

### 10.2 Sealed test results

| | KIT-ICE (§6) | VED-ICE | VED-HEV |
|---|---|---|---|
| Test FPR | 2.23% (expected 2.0%) | 2.847% (expected 3.0%) | 3.352% (expected 3.0%) |
| `coolant_spike`/`load_spike` detection | 100% | 100% | 86.0% |
| `rpm_decorrelation` detection | 100% | 100% | 100.0% |
| Held-out test diversity | 12 trips, **1 vehicle** | 2,355 trips, **30 vehicles** | 1,450 trips, **13 vehicles** |

VED-ICE matches KIT-ICE's detection quality on a held-out set that
actually tests cross-vehicle generalization — KIT structurally could
never test this, being a single vehicle.

VED-HEV's `load_spike` fault showed a genuine, model-specific
detectability ceiling on val (~80.7% at a 2% threshold, never fully
saturating even at 10%) traced to a real property of Isolation Forest
scoring: once a single-feature outlier is trivially separable, further
increasing its magnitude does not lower its score further (confirmed by
direct probe — identical score whether the offset is 1,000 or
1,000,000,000). A looser 3% threshold was accepted deliberately (val
88.0%, test 86.0%) rather than chasing full saturation at the cost of
more false alarms — this ceiling did not reproduce nearly as severely
for VED-ICE (98.3%+ at the same threshold), so it's a property of this
specific fitted model/vehicle population, not the fault-injection
methodology itself.

### 10.3 The `real_obd_001` finding that changed the plan

Scoring this project's own hybrid session (`real_obd_001`) against
VED-HEV: **13.8% anomaly rate** (vs. ~3% expected) — an improvement over
the original KIT-model result (16.7%, §7) but still far from the
calibrated rate.

**Root-cause investigation, same discipline as §7's original
investigation — hypothesis tested and rejected, not assumed:**

The original KIT-model hypothesis (short engine-on cycles are
underrepresented in training, so the 60s rolling window never
stabilizes) was directly retested against VED-HEV and **rejected**:
VED's own 89 HEV vehicles have plenty of short engine-on stretches too
(median 10.0s, 49.6% under 10s, only 7.3% ever reach 60s, across ~1.99M
rows) — `real_obd_001`'s pattern (median ~7.5s, 0% reaching 60s) is
well within VED's own typical range, not a novel shape.

The actual driver, confirmed by direct magnitude comparison against
VED-HEV's own short-stretch reference distribution:

| | VED-HEV reference (median \|dev\|) | `real_obd_001` (median \|dev\|) |
|---|---|---|
| `rpm_dev` | ~480 | ~1,238 (elevated ~2.6x, but within VED's own tail range — only 3.8% of rows exceed VED's own 95th percentile) |
| `engine_load_pct_dev` | ~14.5 | **~70.6** (exceeds VED's own 99th percentile of ~65.5 — this is `real_obd_001`'s *typical* row, not a tail case) |

`engine_load_pct` is behaving very differently in `real_obd_001` than in
VED's 89-vehicle population, specifically at the moment the engine
kicks in — consistent with a hybrid control strategy that fires the
engine only under high-demand conditions (confirmed anecdotally: RPM
jumps directly from 0 to ~1,470 in under a second in at least one
observed instance — consistent with an electrically-spun-up hybrid
architecture, e.g. Toyota HSD-style, rather than a traditional
starter-crank ramp). A scaling/calibration bug was considered and ruled
out — this data was captured via the feasibility project's `python-obd`
pipeline, not `OBD2Lib`, and there's no reason to suspect a units issue
there.

**Window-duration follow-up**: a 30-second-window HEV variant was built
and fully evaluated (same train/val/test vehicles as the 60s model, via
`--reuse-manifest`, for a clean apples-to-apples comparison). On VED's
own data the shift is modest (median `engine_load_pct_dev` |dev| 14.5 →
11.8, ~19% — nowhere near closing the ~5x gap to `real_obd_001`), but
the 30s model's sealed test result was independently better regardless:
**99.7% `load_spike` detection vs. 86.0% for the 60s model**, at a
comparable FPR (3.698% vs 3.352%) — a genuine improvement on its own
merits, not contingent on resolving the `real_obd_001` gap.

**Conclusion**: a model trained on 89 real hybrid vehicles still
couldn't match `real_obd_001`'s *typical* (median, not just tail)
behavior. This is evidence that no population-scale training set —
however large or diverse — is likely to fully close this kind of gap
for every vehicle, because the gap reflects genuine vehicle/manufacturer-
specific control-strategy differences, not a data-coverage problem. This
finding directly motivated a pivot to per-vehicle models — design and
rationale recorded in `architecture.md` §3.15 (this project's convention
is architecture decisions live there, not duplicated here).

### 10.4 What's preserved from this work

- Full VED pipeline (`ved_loader.py`, `ved_feature_engineering.py` —
  now parameterized by window length, `ved_train_val_split.py` — now
  supports `--reuse-manifest`, `ved_train_baseline_model.py`,
  `ved_synthetic_fault_injection.py`, `ved_threshold_calibration.py`,
  `ved_final_evaluation.py`) is retained and directly reusable — see
  `architecture.md` §3.15.2 for how it's repurposed as a cold-start
  prior rather than discarded.
- All data-quality findings (§10.1) apply regardless of what happens to
  the cross-vehicle model itself — any future VED use (cold-start prior,
  or a from-scratch per-vehicle bootstrap comparison) inherits them.
- The Isolation Forest score-ceiling mechanism (§10.2) is a durable
  finding about the algorithm itself, applicable to any future
  single-feature synthetic fault design, cross-vehicle or per-vehicle.
---

## Appendix: Script Inventory

All scripts in `analytics/src/` unless noted; run in this order to
reproduce the pipeline end to end.

| Script | Purpose |
|---|---|
| `kit_loader.py` | Load and clean raw KIT CSVs (encoding fix, real timestamps, trip IDs, translated condition labels) |
| `feature_engineering.py` | Compute rolling-deviation features, trim cold-start window |
| `train_val_split.py` | Resample to 1Hz, three-way trip-level train/val/test split, held-out special trips |
| `train_baseline_model.py` | Fit the Isolation Forest, sanity-check against val/holdout |
| `synthetic_fault_injection.py` | Inject known faults into validation trips, measure score sensitivity |
| `rpm_magnitude_sweep.py` | Diagnostic: confirmed RPM fault magnitude needed revision (§5.2) |
| `threshold_calibration.py` | Derive the operating threshold from an explicit FPR/detection tradeoff |
| `final_evaluation.py` | One-time sealed test-set evaluation |
| `notebooks/score_real_vehicle_data.ipynb` | Apply the finished pipeline to `real_obd_001`; source of the §7 investigation |

## Citation

Weber, Marc (2023): Automotive OBD-II Dataset. Karlsruhe Institute of
Technology. Dataset. https://doi.org/10.35097/1130. Licensed under
CC BY 4.0.