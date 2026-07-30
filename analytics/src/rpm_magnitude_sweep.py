"""
rpm_magnitude_sweep.py — follow-up to step 5, investigating why
rpm_decorrelation detection was weak (17.5% at the 2% FPR threshold,
vs. coolant_spike's 100%) in synthetic_fault_injection.py.

Reuses the SAME injection windows across every magnitude tested (one
per validation trip, picked once) so the comparison isolates the
effect of magnitude alone — not different random moments being
injected each time.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from synthetic_fault_injection import pick_injection_window, FEATURE_COLS, RANDOM_SEED

MAGNITUDES_TO_TEST = [1200, 2000, 3000, 4000, 6000, 8000]


def run_magnitude_sweep(val_df: pd.DataFrame, model, threshold: float, rng: np.random.Generator):
    # Pick windows once — same set of (trip, window) pairs reused for
    # every magnitude below.
    windows = []
    for trip_id, trip_df in val_df.groupby("trip_id"):
        trip_df = trip_df.sort_values("timestamp").reset_index(drop=True)
        window = pick_injection_window(trip_df, rng)
        if window is not None:
            windows.append((trip_id, window))

    rows = []
    for magnitude in MAGNITUDES_TO_TEST:
        deltas = []
        detected = 0
        total = 0
        for trip_id, window in windows:
            injected = window.copy()
            injected["rpm_dev"] += magnitude
            original_scores = model.decision_function(window[FEATURE_COLS])
            injected_scores = model.decision_function(injected[FEATURE_COLS])

            deltas.extend(injected_scores - original_scores)
            detected += (injected_scores < threshold).sum()
            total += len(injected_scores)

        rows.append({
            "magnitude": magnitude,
            "mean_delta": np.mean(deltas),
            "detection_pct_at_threshold": detected / total * 100,
        })

    return pd.DataFrame(rows)


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    val_path = ANALYTICS_DIR / "dataset/processed/kit_val.parquet"
    model_path = ANALYTICS_DIR / "models/isolation_forest_baseline.joblib"
    config_path = ANALYTICS_DIR / "models/threshold_config.json"

    val_df = pd.read_parquet(val_path)
    model = joblib.load(model_path)

    import json
    with open(config_path) as f:
        threshold = json.load(f)["threshold"]

    print(f"Using calibrated threshold: {threshold:.4f} (score below this = anomalous)")
    print(f"Reminder — training data's own rpm_dev range topped out around "
          f"+/-2900 in ordinary driving; magnitudes below span from close to "
          f"that range up to well beyond it.\n")

    rng = np.random.default_rng(RANDOM_SEED)
    results = run_magnitude_sweep(val_df, model, threshold, rng)

    print(results.to_string(index=False, float_format=lambda x: f"{x:.3f}"))