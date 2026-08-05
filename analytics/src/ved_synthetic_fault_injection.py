"""
ved_synthetic_fault_injection.py — inject synthetic faults into VED val
trips and measure Isolation Forest detection sensitivity, same
disclosure/methodology commitment as the KIT pipeline
(synthetic_fault_injection.py + rpm_magnitude_sweep.py combined into one
script here): this is a controlled test of detection sensitivity using
known, deliberately introduced faults — NOT a claim of real fault data.

Two fault types, chosen to be the closest available analogues to KIT's
two faults given VED's different column set (no coolant at all):

- `load_spike`   — offset added to `engine_load_pct_dev`, standing in for
                    KIT's `coolant_spike`. Not a perfect analogue (engine
                    load and coolant temperature are physically different
                    quantities), but it's the deviation-feature fault
                    that plays the same methodological role: an implausible
                    jump in a feature that should move smoothly.
- `rpm_decorrelation` — offset added to `rpm_dev` while `speed_kmh` is
                    left untouched, same fault definition as KIT
                    (simulates e.g. a slipping clutch — engine revs
                    without corresponding vehicle speed change).

Magnitude is expressed as a MULTIPLE OF THE FEATURE'S OWN TRAIN-SET
STANDARD DEVIATION, not a fixed absolute number — this is the direct
lesson from KIT's RPM fault (an offset of 1200 "sounded large" but was
small relative to rpm_dev's own std there, and needed revision after a
dedicated sweep). Anchoring to std from the start means the sweep here is
checking "how many std-widths does it take to detect reliably", the
right question, rather than re-discovering the same mistake.

IMPORTANT: rpm_dev and engine_load_pct_dev have DIFFERENT stds for ICE
vs. HEV (confirmed: rpm_dev std is ~506 for ICE vs. ~865 for HEV, plausibly
reflecting HEV's engine on/off cycling never letting the rolling window
fully stabilize — see model_details.md §7 for the same phenomenon in the
KIT/real_obd_001 investigation). Magnitudes are computed fresh from
whichever train set is passed in — never hardcoded or reused across the
ICE/HEV variants.

Fault windows: one randomly-chosen 30-second window per sampled trip,
paired before/after (same trip, same moment, only the targeted feature
altered) — identical framing to KIT.

No threshold is chosen or applied here — that's threshold_calibration.py's
job. This script reports detection rate at several REFERENCE thresholds
(percentiles of val's own unmodified score distribution) purely to
inform the magnitude sweep; the real calibration happens downstream
using this script's output as one input to that tradeoff table, exactly
as in the KIT pipeline.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

FEATURE_COLS = ["rpm_dev", "engine_load_pct_dev", "speed_kmh"]
WINDOW_SECONDS = 30
RANDOM_SEED = 42

# Reference thresholds only, for sweep reporting — real calibration is a
# separate downstream step.
REFERENCE_FPR_TARGETS = [0.02, 0.05, 0.10]

FAULT_TARGET_COL = {
    "load_spike": "engine_load_pct_dev",
    "rpm_decorrelation": "rpm_dev",
}


def sample_fault_windows(df: pd.DataFrame, n_trips: int, seed: int) -> list[pd.DataFrame]:
    """Pick one random 30s window per sampled trip.

    Only trips with enough rows to contain a full WINDOW_SECONDS span are
    eligible. Returns a list of per-window DataFrames (original,
    unmodified rows — the caller injects the fault on a copy).
    """
    rng = np.random.default_rng(seed)
    trip_groups = list(df.groupby(["VehId", "Trip"]))
    rng.shuffle(trip_groups)

    windows = []
    for (veh, trip), sub in trip_groups:
        sub = sub.sort_values("time")
        span_s = (sub["time"].iloc[-1] - sub["time"].iloc[0]).total_seconds()
        if span_s < WINDOW_SECONDS:
            continue

        max_start_offset = span_s - WINDOW_SECONDS
        start_offset = rng.uniform(0, max_start_offset)
        window_start = sub["time"].iloc[0] + pd.Timedelta(seconds=start_offset)
        window_end = window_start + pd.Timedelta(seconds=WINDOW_SECONDS)

        window = sub[(sub["time"] >= window_start) & (sub["time"] < window_end)]
        if window[FEATURE_COLS].isnull().any().any():
            continue  # skip windows touching any null feature value
        if len(window) < 3:
            continue  # too few rows to be a meaningful paired comparison

        windows.append(window)
        if len(windows) >= n_trips:
            break

    return windows


def inject_fault(window: pd.DataFrame, fault_type: str, magnitude: float) -> pd.DataFrame:
    target_col = FAULT_TARGET_COL[fault_type]
    faulted = window.copy()
    faulted[target_col] = faulted[target_col] + magnitude
    return faulted


def run_sweep(
    model,
    val_df: pd.DataFrame,
    fault_type: str,
    std_multiples: list[float],
    feature_std: float,
    n_trips: int,
    seed: int,
) -> pd.DataFrame:
    windows = sample_fault_windows(val_df, n_trips, seed)
    print(f"  sampled {len(windows)} fault windows (requested {n_trips})", file=sys.stderr)

    # Reference thresholds from val's own unmodified score distribution.
    val_scores_all = model.decision_function(val_df[FEATURE_COLS].dropna().to_numpy())
    ref_thresholds = {
        fpr: float(np.percentile(val_scores_all, fpr * 100)) for fpr in REFERENCE_FPR_TARGETS
    }

    rows = []
    for mult in std_multiples:
        magnitude = mult * feature_std
        detections = {fpr: 0 for fpr in REFERENCE_FPR_TARGETS}
        total = 0
        for window in windows:
            faulted = inject_fault(window, fault_type, magnitude)
            scores = model.decision_function(faulted[FEATURE_COLS].to_numpy())
            for fpr, thresh in ref_thresholds.items():
                detections[fpr] += int((scores < thresh).any())
            total += 1

        row = {"std_multiple": mult, "magnitude": magnitude, "n_windows": total}
        for fpr in REFERENCE_FPR_TARGETS:
            row[f"detect_rate_at_{int(fpr*100)}pct_fpr"] = detections[fpr] / total if total else float("nan")
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True, help="Path to trained model .joblib")
    parser.add_argument("--train", type=Path, required=True, help="Path to *_train.parquet (source of feature std for magnitude sizing)")
    parser.add_argument("--val", type=Path, required=True, help="Path to *_val.parquet (source of fault-injection windows)")
    parser.add_argument("--fault-type", choices=list(FAULT_TARGET_COL), required=True)
    parser.add_argument(
        "--std-multiples",
        type=float,
        nargs="+",
        default=[0.5, 1.0, 2.0, 3.0, 5.0, 8.0],
        help="Fault magnitudes to sweep, as multiples of the target feature's own train-set std",
    )
    parser.add_argument("--n-trips", type=int, default=300, help="Number of fault windows to sample")
    parser.add_argument("--output-csv", type=Path, default=None, help="Optional path to write the sweep results table")
    args = parser.parse_args()

    print(f"Loading model: {args.model}", file=sys.stderr)
    bundle = joblib.load(args.model)
    model = bundle["model"]

    print(f"Loading train (for std): {args.train}", file=sys.stderr)
    train_df = pd.read_parquet(args.train, columns=FEATURE_COLS)
    target_col = FAULT_TARGET_COL[args.fault_type]
    feature_std = train_df[target_col].std()
    print(f"  {target_col} train std: {feature_std:.4f}", file=sys.stderr)

    print(f"Loading val: {args.val}", file=sys.stderr)
    val_df = pd.read_parquet(args.val, columns=["VehId", "Trip", "time"] + FEATURE_COLS)

    print(f"\nRunning magnitude sweep for fault_type={args.fault_type}...", file=sys.stderr)
    results = run_sweep(
        model, val_df, args.fault_type, args.std_multiples, feature_std,
        n_trips=args.n_trips, seed=RANDOM_SEED,
    )

    print(f"\n{results.to_string(index=False)}", file=sys.stderr)

    if args.output_csv:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        results.to_csv(args.output_csv, index=False)
        print(f"\nWrote {args.output_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()