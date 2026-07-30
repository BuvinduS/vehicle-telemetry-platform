"""
threshold_calibration.py — step 5b of the pipeline (architecture.md
§3.13).

Replaces sklearn's IsolationForest(contamination="auto") — which sets
a threshold via a formula from the original paper, with no relation to
how rare real anomalies should be in THIS data — with a threshold
chosen from an actual tradeoff: at each candidate cutoff, what
fraction of real normal driving (kit_val.parquet) would be wrongly
flagged, versus what fraction of known synthetic faults
(injection_test_results.parquet, from synthetic_fault_injection.py)
would be correctly caught.

Uses validation data only — test stays sealed until final evaluation.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

FEATURE_COLS = ["coolant_temp_c_dev", "rpm_dev", "speed_kmh"]

# Candidate false-positive rates to evaluate — expressed as "what % of
# real normal driving would this threshold flag." Framed this way
# (not as raw score values) because it's the interpretable quantity a
# person actually has intuition for.
CANDIDATE_FPR_PERCENTILES = [0.5, 1, 2, 5, 10]


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    val_path = ANALYTICS_DIR / "dataset/processed/kit_val.parquet"
    injection_path = ANALYTICS_DIR / "dataset/processed/injection_test_results.parquet"
    model_path = ANALYTICS_DIR / "models/isolation_forest_baseline.joblib"
    config_path = ANALYTICS_DIR / "models/threshold_config.json"

    val_df = pd.read_parquet(val_path)
    injection_results = pd.read_parquet(injection_path)
    model = joblib.load(model_path)

    normal_scores = model.decision_function(val_df[FEATURE_COLS])
    print(f"Scored {len(normal_scores):,} real normal-driving rows from validation\n")

    rows = []
    for pct in CANDIDATE_FPR_PERCENTILES:
        threshold = np.percentile(normal_scores, pct)
        actual_fpr = (normal_scores < threshold).mean() * 100

        row = {"target_fpr_pct": pct, "threshold": threshold, "actual_fpr_pct": actual_fpr}

        for fault_name in injection_results["fault"].unique():
            fault_scores = injection_results.loc[
                injection_results["fault"] == fault_name, "injected_score"
            ]
            detection_rate = (fault_scores < threshold).mean() * 100
            row[f"{fault_name}_detection_pct"] = detection_rate

        rows.append(row)

    table = pd.DataFrame(rows)
    print("Threshold tradeoff table:")
    print(table.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

    # Default recommendation: the 2% FPR row — flags roughly 1 in 50
    # real normal driving moments (a defensible "genuinely rare"
    # operating point) while checking the table confirms detection
    # rates are still high at that cutoff, not just at looser cutoffs.
    chosen = table[table["target_fpr_pct"] == 2].iloc[0]
    print(f"\nRecommended threshold (2% FPR operating point): {chosen['threshold']:.4f}")

    config = {
        "threshold": float(chosen["threshold"]),
        "target_fpr_pct": 2.0,
        "actual_fpr_pct": float(chosen["actual_fpr_pct"]),
        "feature_cols": FEATURE_COLS,
        "note": "score < threshold means anomalous. Chosen from val-set "
                "FPR/detection tradeoff, not sklearn's contamination='auto'.",
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nSaved threshold config to: {config_path}")