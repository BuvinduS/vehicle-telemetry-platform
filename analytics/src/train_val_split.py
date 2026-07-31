"""
train_val_split.py — step 3 of the pipeline (architecture.md §3.13).

Takes kit_features.parquet and:
  1. Resamples each trip to ~1Hz (the raw data is forward-filled at
     ~10Hz, but individual PIDs only genuinely update a fraction of
     that often — see kit_loader.py's original inspection notes).
  2. Splits trips (not rows) into train/validation, so validation
     trips are ones the model has never seen any row of.
  3. Holds out the four special-situation trips (hard_braking,
     black_ice, acceleration_test, measurement_error) entirely,
     separate from the train/val split — informal sanity-check
     material for later, not part of the "normal" pool at all.
"""

from pathlib import Path

import numpy as np
import pandas as pd

FEATURE_COLS = ["coolant_temp_c_dev", "rpm_dev", "speed_kmh"]

# Conditions treated as ordinary driving, eligible for the
# train/validation split. Everything else is a one-off special
# situation, held out separately.
NORMAL_CONDITIONS = {"normal", "free_flow", "traffic_jam"}

RESAMPLE_RATE = "1s"
TRAIN_FRACTION = 0.70
VAL_FRACTION = 0.15
TEST_FRACTION = 0.15  # sealed until final evaluation — see chat notes
RANDOM_SEED = 42


def resample_trip(trip_df: pd.DataFrame) -> pd.DataFrame:
    """
    Downsample one trip to one row per second. Uses .last() per bucket
    (the most recent forward-filled reading within each 1s window)
    rather than .mean() — averaging would blur real short-lived spikes
    (e.g. a brief coolant excursion) into a smoothed value the whole
    point of anomaly detection is to still catch.
    """
    trip_df = trip_df.set_index("timestamp").sort_index()
    resampled = trip_df.resample(RESAMPLE_RATE).last()
    resampled = resampled.dropna(subset=FEATURE_COLS)
    resampled = resampled.reset_index()
    return resampled


def build_split(df: pd.DataFrame):
    normal_mask = df["condition"].isin(NORMAL_CONDITIONS)
    normal_df = df[normal_mask].copy()
    special_df = df[~normal_mask].copy()

    print(f"Normal-pool trips: {normal_df['trip_id'].nunique()}")
    print(f"Held-out special trips: {special_df['trip_id'].nunique()} "
          f"({sorted(special_df['condition'].unique())})")

    # Resample each normal-pool trip independently, then recombine.
    resampled_trips = [
        resample_trip(trip_df) for _, trip_df in normal_df.groupby("trip_id")
    ]
    normal_resampled = pd.concat(resampled_trips, ignore_index=True)

    # Split by whole trip, not by row. Three-way: train (fit the
    # model), val (calibrate decisions, e.g. the fault-injection
    # threshold work coming next), test (touched exactly once, at the
    # very end, after every decision is already locked in — the only
    # number that's an honest estimate of real performance).
    trip_ids = sorted(normal_resampled["trip_id"].unique())
    rng = np.random.default_rng(RANDOM_SEED)
    shuffled = rng.permutation(trip_ids)

    n = len(trip_ids)
    n_val = max(1, round(n * VAL_FRACTION))
    n_test = max(1, round(n * TEST_FRACTION))
    # train gets whatever's left, not a separately-rounded fraction —
    # avoids the three counts silently failing to add up to n due to
    # independent rounding of all three fractions.
    val_ids = set(shuffled[:n_val])
    test_ids = set(shuffled[n_val:n_val + n_test])
    train_ids = set(shuffled[n_val + n_test:])

    train_df = normal_resampled[normal_resampled["trip_id"].isin(train_ids)]
    val_df = normal_resampled[normal_resampled["trip_id"].isin(val_ids)]
    test_df = normal_resampled[normal_resampled["trip_id"].isin(test_ids)]

    return train_df, val_df, test_df, special_df


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    in_path = ANALYTICS_DIR / "dataset/processed/kit_features.parquet"
    train_path = ANALYTICS_DIR / "dataset/processed/kit_train.parquet"
    val_path = ANALYTICS_DIR / "dataset/processed/kit_val.parquet"
    test_path = ANALYTICS_DIR / "dataset/processed/kit_test.parquet"
    holdout_path = ANALYTICS_DIR / "dataset/processed/kit_holdout_special.parquet"

    print(f"Loading: {in_path}")
    df = pd.read_parquet(in_path)
    print(f"Loaded {len(df):,} rows across {df['trip_id'].nunique()} trips\n")

    train_df, val_df, test_df, special_df = build_split(df)

    print(f"\nAfter 1Hz resampling:")
    print(f"  Train: {len(train_df):,} rows, {train_df['trip_id'].nunique()} trips")
    print(f"  Val:   {len(val_df):,} rows, {val_df['trip_id'].nunique()} trips")
    print(f"  Test:  {len(test_df):,} rows, {test_df['trip_id'].nunique()} trips "
          f"(SEALED — no exploration past this point until final evaluation)")
    print(f"  Held-out special (not resampled): {len(special_df):,} rows, "
          f"{special_df['trip_id'].nunique()} trips")

    normal_total = len(df[df["condition"].isin(NORMAL_CONDITIONS)])
    resampled_total = len(train_df) + len(val_df) + len(test_df)
    print(f"\nCompression from resampling: "
          f"{normal_total:,} -> {resampled_total:,} rows "
          f"({resampled_total / normal_total * 100:.1f}%)")

    print("\nTrain feature summary:")
    print(train_df[FEATURE_COLS].describe())

    # Explicit manifest: which trip went into which split, by filename
    # (not just trip_id, which is only meaningful in the context of
    # this specific loader run) — so "which trips trained the model"
    # is answerable by reading a file, not by re-deriving it from the
    # parquet outputs or trusting the random seed produced the same
    # result as last time.
    manifest_rows = []
    for split_name, split_df in [("train", train_df), ("val", val_df),
                                   ("test", test_df), ("holdout_special", special_df)]:
        trips = split_df[["trip_id", "source_file", "condition"]].drop_duplicates()
        trips["split"] = split_name
        manifest_rows.append(trips)
    manifest = pd.concat(manifest_rows, ignore_index=True).sort_values("trip_id")

    manifest_path = ANALYTICS_DIR / "dataset/processed/split_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"\nSplit manifest ({len(manifest)} trips):")
    print(manifest.to_string(index=False))

    train_df.to_parquet(train_path, index=False)
    val_df.to_parquet(val_path, index=False)
    test_df.to_parquet(test_path, index=False)
    special_df.to_parquet(holdout_path, index=False)

    print(f"\nSaved:\n  {train_path}\n  {val_path}\n  {test_path}\n  "
          f"{holdout_path}\n  {manifest_path}")