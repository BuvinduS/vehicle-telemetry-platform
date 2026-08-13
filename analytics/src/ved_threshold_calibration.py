"""
ved_threshold_calibration.py — derive the operating threshold for a VED
model variant (ICE or HEV) from an explicit FPR/detection tradeoff, same
principle as the KIT pipeline's threshold_calibration.py: sklearn's
`contamination="auto"` is NOT a target rate and is not used here. Instead,
candidate thresholds (expressed as target false-positive rates against
real, unmodified val driving) are swept, and at each candidate the
detection rate against BOTH synthetic fault types (at a FIXED magnitude,
already settled via ved_synthetic_fault_injection.py's sweep — this
script does not re-sweep magnitude) is measured directly.

The chosen threshold should be the TIGHTEST (lowest target FPR, fewest
false alarms) candidate that doesn't cost detection sensitivity relative
to looser candidates — i.e. going looser stops buying anything further.
This is a real decision to make from the printed table, not something
this script picks automatically, because ICE and HEV are not guaranteed
to land on the same answer (see the chat discussion: HEV's load_spike
fault showed a genuine, model-specific detectability ceiling that
partially recovers at looser thresholds — 80.7% at 2% FPR vs 98% at 10%
FPR — which ICE's load_spike does not exhibit to nearly the same degree).
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

RANDOM_SEED = 42

CANDIDATE_FPR_TARGETS = [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True, help="Used only to compute each fault feature's std for magnitude sizing")
    parser.add_argument("--val", type=Path, required=True)
    parser.add_argument("--std-multiple", type=float, default=5.0, help="Fixed fault magnitude, as a multiple of the target feature's train std (settled separately via the magnitude sweep)")
    parser.add_argument("--n-trips", type=int, default=300)
    args = parser.parse_args()

    bundle = joblib.load(args.model)
    model = bundle["model"]

    train_df = pd.read_parquet(args.train, columns=FEATURE_COLS)
    val_df = pd.read_parquet(args.val, columns=["VehId", "Trip", "time"] + FEATURE_COLS)

    val_scores_all = model.decision_function(val_df[FEATURE_COLS].dropna().to_numpy())

    # Fixed, pre-computed fault windows per fault type (same windows reused
    # across every candidate threshold in the sweep below — only the
    # threshold changes, not the underlying fault instances).
    windows = sample_fault_windows(val_df, args.n_trips, seed=RANDOM_SEED)
    print(f"Using {len(windows)} fault windows per fault type", file=sys.stderr)

    fault_scores: dict[str, list[np.ndarray]] = {}
    for fault_type, target_col in FAULT_TARGET_COL.items():
        std = train_df[target_col].std()
        magnitude = args.std_multiple * std
        print(f"  {fault_type}: magnitude={magnitude:.2f} ({args.std_multiple}x std of {target_col}={std:.2f})", file=sys.stderr)
        scored = []
        for w in windows:
            faulted = inject_fault(w, fault_type, magnitude)
            scored.append(model.decision_function(faulted[FEATURE_COLS].to_numpy()))
        fault_scores[fault_type] = scored

    rows = []
    for target_fpr in CANDIDATE_FPR_TARGETS:
        threshold = np.percentile(val_scores_all, target_fpr)
        actual_fpr = 100 * (val_scores_all < threshold).mean()

        row = {"target_fpr_pct": target_fpr, "threshold": threshold, "actual_val_fpr_pct": actual_fpr}
        for fault_type, scored_windows in fault_scores.items():
            detected = sum(1 for s in scored_windows if (s < threshold).any())
            row[f"{fault_type}_detect_rate"] = detected / len(scored_windows)
        rows.append(row)

    results = pd.DataFrame(rows)
    print()
    print(results.to_string(index=False))

    print(
        "\nPick the tightest (lowest target_fpr_pct) row where both fault-type "
        "detect rates are at or near their saturation value (the value they "
        "hold at the loosest thresholds in this table) — going looser than "
        "that point spends false-alarm budget without buying more detection.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()