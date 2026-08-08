"""
ved_final_evaluation.py — sealed test-set evaluation for a VED model
variant (ICE or HEV). Run exactly once, after every design decision
(features, split, fault magnitude, threshold) is already finalized using
only train/val — same discipline as the KIT pipeline's
final_evaluation.py. No further tuning happens after this result is
observed.

Unlike the calibration/sweep scripts, this script does NOT search over
anything. It takes the fixed threshold VALUE (not a target FPR to
recompute) and the fixed fault magnitude (as a std-multiple, applied to
TRAIN std — same convention as every other script in this pipeline) as
required arguments, and reports:

- Actual FPR on test's own unmodified score distribution, using the
  fixed threshold as-is (this may differ from the val-measured FPR —
  that's expected and is the entire point of a sealed test set, not a
  bug to chase).
- Detection rate for both fault types, injected into a fresh sample of
  TEST trips (never touched by any prior script in this pipeline) at
  the fixed magnitude.

Per the chat discussion: HEV's load_spike fault is known, from val, to
not fully saturate even at loose thresholds (a genuine, disclosed model
characteristic, not a bug) — the 3% threshold was kept anyway, accepting
~88% val detection as good enough. This script does not change that
decision; it only measures how that already-made decision performs on
data it's never seen.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ved_synthetic_fault_injection import (  # noqa: E402
    FEATURE_COLS,
    FAULT_TARGET_COL,
    sample_fault_windows,
    inject_fault,
)

# Different seed from the val-based scripts (RANDOM_SEED = 42 there) —
# deliberate: test windows must be a genuinely fresh sample, not
# incidentally reproducing the same window-selection RNG state used
# throughout calibration.
TEST_RANDOM_SEED = 1337


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True, help="Used only to compute each fault feature's std for magnitude sizing (must match what calibration used)")
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--threshold", type=float, required=True, help="Fixed score threshold value, locked in from val calibration (NOT a target FPR)")
    parser.add_argument("--std-multiple", type=float, default=5.0, help="Fault magnitude, as a multiple of train std (must match what calibration used)")
    parser.add_argument("--n-trips", type=int, default=300)
    parser.add_argument("--confirm-sealed", action="store_true", required=True, help="Explicit acknowledgment this is the one-time sealed run, not a re-tunable step")
    args = parser.parse_args()

    print("=" * 70, file=sys.stderr)
    print("SEALED TEST-SET EVALUATION — run once, no further tuning after this.", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    bundle = joblib.load(args.model)
    model = bundle["model"]

    train_df = pd.read_parquet(args.train, columns=FEATURE_COLS)
    test_df = pd.read_parquet(args.test, columns=["VehId", "Trip", "time"] + FEATURE_COLS)
    print(f"\nTest set: {len(test_df):,} rows, {test_df.VehId.nunique()} vehicles, "
          f"{test_df.groupby(['VehId','Trip']).ngroups} trips", file=sys.stderr)

    test_scores_clean = test_df[FEATURE_COLS].dropna().to_numpy()
    test_scores = model.decision_function(test_scores_clean)

    actual_fpr = 100 * (test_scores < args.threshold).mean()
    print(f"\nThreshold (fixed, from val calibration): {args.threshold:.6f}", file=sys.stderr)
    print(f"Actual FPR on test: {actual_fpr:.3f}%", file=sys.stderr)

    windows = sample_fault_windows(test_df, args.n_trips, seed=TEST_RANDOM_SEED)
    print(f"\nSampled {len(windows)} fresh test fault windows per fault type", file=sys.stderr)

    print(f"\n{'fault_type':<20s} {'magnitude':>12s} {'detect_rate':>12s}", file=sys.stderr)
    results = {}
    for fault_type, target_col in FAULT_TARGET_COL.items():
        std = train_df[target_col].std()
        magnitude = args.std_multiple * std
        detected = 0
        for w in windows:
            faulted = inject_fault(w, fault_type, magnitude)
            scores = model.decision_function(faulted[FEATURE_COLS].to_numpy())
            if (scores < args.threshold).any():
                detected += 1
        rate = detected / len(windows)
        results[fault_type] = rate
        print(f"{fault_type:<20s} {magnitude:>12.2f} {rate:>12.3f}", file=sys.stderr)

    print("\n" + "=" * 70, file=sys.stderr)
    print("RESULT (final, not to be re-tuned against):", file=sys.stderr)
    print(f"  Actual test FPR: {actual_fpr:.3f}%", file=sys.stderr)
    for fault_type, rate in results.items():
        print(f"  {fault_type} detection: {100*rate:.1f}%", file=sys.stderr)
    print("=" * 70, file=sys.stderr)


if __name__ == "__main__":
    main()