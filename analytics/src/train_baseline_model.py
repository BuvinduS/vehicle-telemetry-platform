"""
train_baseline_model.py — step 4 of the pipeline (architecture.md §3.13).

Trains a baseline Isolation Forest on the resampled, feature-engineered
KIT training trips. No hyperparameter tuning at this stage — the point
is a working end-to-end baseline to sanity-check before any tuning.

Isolation Forest needs no feature scaling (see chat notes: it splits
on one randomly-chosen feature's own range at a time, never compares
magnitudes across features) — feeding it the raw deviation/speed
values from feature_engineering.py is correct as-is.
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

FEATURE_COLS = ["coolant_temp_c_dev", "rpm_dev", "speed_kmh"]
RANDOM_SEED = 42  # same seed used for the train/val split, for consistency


def summarize_predictions(name: str, model: IsolationForest, df: pd.DataFrame):
    """
    predict() returns 1 for 'normal' (inlier), -1 for 'anomalous'
    (outlier). decision_function() gives the underlying continuous
    score the +-1 label is thresholded from — negative means anomalous,
    positive means normal, magnitude reflects how confidently so.
    """
    X = df[FEATURE_COLS]
    preds = model.predict(X)
    scores = model.decision_function(X)

    pct_anomalous = (preds == -1).mean() * 100
    print(f"{name}: {len(df):,} rows, {df['trip_id'].nunique()} trips "
          f"-> {pct_anomalous:.1f}% flagged anomalous "
          f"(score range {scores.min():.3f} to {scores.max():.3f}, "
          f"mean {scores.mean():.3f})")


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    train_path = ANALYTICS_DIR / "dataset/processed/kit_train.parquet"
    val_path = ANALYTICS_DIR / "dataset/processed/kit_val.parquet"
    holdout_path = ANALYTICS_DIR / "dataset/processed/kit_holdout_special.parquet"
    model_path = ANALYTICS_DIR / "models/isolation_forest_baseline.joblib"

    train_df = pd.read_parquet(train_path)
    val_df = pd.read_parquet(val_path)
    holdout_df = pd.read_parquet(holdout_path)

    print(f"Training on {len(train_df):,} rows across "
          f"{train_df['trip_id'].nunique()} trips\n")

    model = IsolationForest(
        n_estimators=100,      # number of random trees in the forest — sklearn's default, no tuning yet
        contamination="auto",  # let sklearn set the anomaly threshold via the original paper's method, rather than us guessing an expected anomaly rate
        random_state=RANDOM_SEED,
    )
    model.fit(train_df[FEATURE_COLS])

    print("=== Sanity checks (not formal validation) ===\n")

    summarize_predictions("Train (seen during fitting)", model, train_df)
    summarize_predictions("Validation (held-out normal trips)", model, val_df)

    print()
    for condition in sorted(holdout_df["condition"].unique()):
        subset = holdout_df[holdout_df["condition"] == condition]
        summarize_predictions(f"Holdout - {condition}", model, subset)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path)
    print(f"\nSaved model to: {model_path}")