"""
final_evaluation.py — step 6 of the pipeline (architecture.md §3.13).

The ONE-TIME evaluation against kit_test.parquet. Everything upstream
of this (features, split ratios, fault magnitudes, threshold) was
decided using only train/val/holdout data — test was never looked at
until now. Whatever comes out of this run is reported as-is; no
further tuning happens based on these results. If something looks
worse than validation suggested, that's a documented finding for the
writeup, not a reason to iterate further against this same test set.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from synthetic_fault_injection import run_injection_test, FAULTS, FEATURE_COLS, RANDOM_SEED


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    test_path = ANALYTICS_DIR / "dataset/processed/kit_test.parquet"
    model_path = ANALYTICS_DIR / "models/isolation_forest_baseline.joblib"
    config_path = ANALYTICS_DIR / "models/threshold_config.json"

    test_df = pd.read_parquet(test_path)
    model = joblib.load(model_path)
    with open(config_path) as f:
        config = json.load(f)
    threshold = config["threshold"]

    print("=" * 60)
    print("SEALED TEST SET EVALUATION — run once, reported as-is")
    print("=" * 60)
    print(f"\nTest set: {len(test_df):,} rows, {test_df['trip_id'].nunique()} trips")
    print(f"Threshold: {threshold:.4f} (calibrated on validation, "
          f"target 2% FPR)\n")

    # --- Real-data false positive rate ---
    test_scores = model.decision_function(test_df[FEATURE_COLS])
    actual_fpr = (test_scores < threshold).mean() * 100
    print(f"--- Real normal-driving false positive rate ---")
    print(f"Expected (from validation calibration): 2.0%")
    print(f"Actual (test set):                       {actual_fpr:.2f}%")

    percentiles = pd.Series(test_scores).describe(percentiles=[0.01, 0.05, 0.1, 0.5, 0.9])
    print(f"\nTest score percentiles: 1%={percentiles['1%']:.3f}  "
          f"5%={percentiles['5%']:.3f}  10%={percentiles['10%']:.3f}  "
          f"50%={percentiles['50%']:.3f}  90%={percentiles['90%']:.3f}")

    # --- Synthetic fault detection on genuinely unseen trips ---
    print(f"\n--- Synthetic fault detection (unseen test trips) ---")
    rng = np.random.default_rng(RANDOM_SEED)
    injection_results = run_injection_test(test_df, model, rng)

    for fault_name in FAULTS:
        subset = injection_results[injection_results["fault"] == fault_name]
        detection_rate = (subset["injected_score"] < threshold).mean() * 100
        print(f"{fault_name}: {detection_rate:.1f}% detected "
              f"({len(subset)} rows tested, magnitude={FAULTS[fault_name]['offset']})")

    print("\n" + "=" * 60)
    print("This is the final, sealed result for this model version.")
    print("=" * 60)