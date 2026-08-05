"""
ved_train_baseline_model.py — fit the Isolation Forest for a VED-derived
model variant (ICE or HEV), same algorithm/hyperparameters as the KIT
baseline (`train_baseline_model.py`), applied here to whichever
engine-type split is passed in.

Deliberately NOT engine-type-specific in this script's logic — it just
fits a model against three named feature columns from a train parquet
and sanity-checks against val. The ICE vs. HEV distinction lives entirely
in which files you point it at (`ved_ice_train.parquet` vs.
`ved_hev_train.parquet`), consistent with keeping the two models
otherwise identical in method so any difference in their results reflects
the vehicles/data, not two different pipelines.

No loss function / MSE here, per the chat discussion: Isolation Forest is
unsupervised and doesn't optimize against a labeled target. What this
script prints (train vs. val score-percentile comparison) is a rough
"does val look like train" sanity check only — NOT model evaluation.
Real evaluation (FPR / detection-rate) happens in later scripts
(synthetic_fault_injection.py, threshold_calibration.py,
final_evaluation.py) once ported, exactly as in the KIT pipeline.

Rows with any null in the three feature columns are dropped before
fitting — sklearn's IsolationForest can't handle NaN, and null rate on
these columns is already confirmed under 0.5% (ved_loader.py /
ved_feature_engineering.py), so this drops a negligible fraction, not
something that changes the vehicle-level split proportions in any
meaningful way.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

HERE = Path(__file__).resolve().parent

FEATURE_COLS = ["rpm_dev", "engine_load_pct_dev", "speed_kmh"]

N_ESTIMATORS = 100
RANDOM_STATE = 42


def load_features(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=["VehId", "Trip", "time"] + FEATURE_COLS)
    n_before = len(df)
    df = df.dropna(subset=FEATURE_COLS)
    n_dropped = n_before - len(df)
    if n_dropped:
        print(
            f"  dropped {n_dropped:,} of {n_before:,} rows ({100*n_dropped/n_before:.3f}%) "
            f"with null feature values",
            file=sys.stderr,
        )
    return df


def score_summary(scores: np.ndarray) -> dict:
    percentiles = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    return {f"p{p}": float(np.percentile(scores, p)) for p in percentiles}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True, help="Path to *_train.parquet")
    parser.add_argument("--val", type=Path, required=True, help="Path to *_val.parquet (sanity check only, not tuned against)")
    parser.add_argument("--output-model", type=Path, required=True, help="Path to write the fitted model (joblib)")
    args = parser.parse_args()

    print(f"Loading train: {args.train}", file=sys.stderr)
    train_df = load_features(args.train)
    print(f"  {len(train_df):,} rows, {train_df.VehId.nunique()} vehicles", file=sys.stderr)

    print(f"Loading val: {args.val}", file=sys.stderr)
    val_df = load_features(args.val)
    print(f"  {len(val_df):,} rows, {val_df.VehId.nunique()} vehicles", file=sys.stderr)

    X_train = train_df[FEATURE_COLS].to_numpy()

    print(
        f"\nFitting IsolationForest(n_estimators={N_ESTIMATORS}, random_state={RANDOM_STATE}) "
        f"on {len(X_train):,} rows, {len(FEATURE_COLS)} features...",
        file=sys.stderr,
    )
    model = IsolationForest(n_estimators=N_ESTIMATORS, random_state=RANDOM_STATE, n_jobs=-1)
    model.fit(X_train)

    train_scores = model.decision_function(X_train)
    val_scores = model.decision_function(val_df[FEATURE_COLS].to_numpy())

    print("\nScore percentiles (higher = more normal, per sklearn convention):", file=sys.stderr)
    train_p = score_summary(train_scores)
    val_p = score_summary(val_scores)
    print(f"{'percentile':>10s}  {'train':>10s}  {'val':>10s}", file=sys.stderr)
    for k in train_p:
        print(f"{k:>10s}  {train_p[k]:>10.4f}  {val_p[k]:>10.4f}", file=sys.stderr)

    print(
        "\n(This is a sanity check only — 'does val's score distribution look "
        "like train's', not a model evaluation. Real evaluation happens via "
        "synthetic fault injection + threshold calibration, not shown here.)",
        file=sys.stderr,
    )

    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_cols": FEATURE_COLS}, args.output_model)
    print(f"\nWrote model: {args.output_model}", file=sys.stderr)


if __name__ == "__main__":
    main()