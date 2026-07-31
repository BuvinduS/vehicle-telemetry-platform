"""
synthetic_fault_injection.py — step 5 of the pipeline (architecture.md
§3.13).

Injects two known, disclosed synthetic faults into real VALIDATION
trips (never test — test stays sealed until final evaluation), then
checks whether the trained model's anomaly score actually reacts.

This is a controlled sensitivity test, not a claim of real fault data
— see architecture.md §3.13's explicit disclosure language. Injecting
directly into feature columns (not raw sensor values re-run through
the rolling-median pipeline) is a deliberate simplification: we're
testing "does the model notice an unusual feature value," not
re-validating the preprocessing pipeline itself.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

FEATURE_COLS = ["coolant_temp_c_dev", "rpm_dev", "speed_kmh"]
WINDOW_SECONDS = 30  # at 1Hz post-resampling, this is 30 rows
RANDOM_SEED = 42

# Magnitudes chosen to be clearly outside the normal deviation range
# we saw in feature_engineering.py's summary (coolant_dev max ~11,
# rpm_dev max ~2900) — these should read as unambiguous faults, not
# borderline cases, since the point right now is "can the model
# detect an obvious fault at all," not fine-grained sensitivity.
#
# rpm_decorrelation's offset was originally 1200 — a magnitude sweep
# (rpm_magnitude_sweep.py) showed this badly underestimated how large
# an offset needs to be relative to RPM's own naturally wide variance
# (std ~373 in ordinary driving): detection was only 17.5% at 1200,
# climbing to 95.3% at 2000, and fully saturating (100%, stable
# mean_delta) from 3000 onward. Updated to 3000 accordingly — the
# earlier weak result was a test-design issue, not a real model
# limitation. Lesson: fault magnitudes must be sized relative to each
# feature's own observed spread, not picked by "sounds big enough."
FAULTS = {
    "coolant_spike": {
        "column": "coolant_temp_c_dev",
        "offset": 20.0,  # simulates a stuck thermostat / coolant loss
    },
    "rpm_decorrelation": {
        "column": "rpm_dev",
        "offset": 3000.0,  # simulates e.g. a slipping clutch: RPM rises, speed doesn't
    },
}


def pick_injection_window(trip_df: pd.DataFrame, rng: np.random.Generator):
    """Pick a random WINDOW_SECONDS-long contiguous slice, away from the trip's edges."""
    n = len(trip_df)
    if n <= WINDOW_SECONDS * 2:
        return None  # trip too short to safely pick a window
    start = rng.integers(WINDOW_SECONDS, n - WINDOW_SECONDS * 2)
    return trip_df.iloc[start:start + WINDOW_SECONDS]


def run_injection_test(val_df: pd.DataFrame, model, rng: np.random.Generator):
    results = []

    for trip_id, trip_df in val_df.groupby("trip_id"):
        trip_df = trip_df.sort_values("timestamp").reset_index(drop=True)
        window = pick_injection_window(trip_df, rng)
        if window is None:
            continue

        original_scores = model.decision_function(window[FEATURE_COLS])

        for fault_name, fault_spec in FAULTS.items():
            injected = window.copy()
            injected[fault_spec["column"]] += fault_spec["offset"]
            injected_scores = model.decision_function(injected[FEATURE_COLS])

            for orig_score, inj_score in zip(original_scores, injected_scores):
                results.append({
                    "trip_id": trip_id,
                    "fault": fault_name,
                    "original_score": orig_score,
                    "injected_score": inj_score,
                    "delta": inj_score - orig_score,
                    "flipped_to_anomalous": (orig_score > 0) and (inj_score < 0),
                })

    return pd.DataFrame(results)


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    val_path = ANALYTICS_DIR / "dataset/processed/kit_val.parquet"
    model_path = ANALYTICS_DIR / "models/isolation_forest_baseline.joblib"

    val_df = pd.read_parquet(val_path)
    model = joblib.load(model_path)
    rng = np.random.default_rng(RANDOM_SEED)

    print(f"Running injection test on {val_df['trip_id'].nunique()} validation trips\n")

    results = run_injection_test(val_df, model, rng)

    for fault_name in FAULTS:
        subset = results[results["fault"] == fault_name]
        print(f"=== {fault_name} ===")
        print(f"  Rows tested: {len(subset)}")
        print(f"  Mean score BEFORE injection: {subset['original_score'].mean():.4f}")
        print(f"  Mean score AFTER injection:  {subset['injected_score'].mean():.4f}")
        print(f"  Mean delta (drop): {subset['delta'].mean():.4f}")
        print(f"  Flipped normal->anomalous: {subset['flipped_to_anomalous'].sum()} "
              f"/ {len(subset)} ({subset['flipped_to_anomalous'].mean()*100:.1f}%)")
        print()

    out_path = ANALYTICS_DIR / "dataset/processed/injection_test_results.parquet"
    results.to_parquet(out_path, index=False)
    print(f"Saved detailed results to: {out_path}")