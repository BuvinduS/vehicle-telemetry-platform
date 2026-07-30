"""
feature_engineering.py — step 2 of the pipeline (architecture.md §3.13).

Takes the cleaned, combined dataset from kit_loader.py and derives the
actual model-input features:
  - coolant_temp_dev, rpm_dev: deviation from each trip's OWN trailing
    60s rolling median (high cross-vehicle fragility — see chat notes)
  - throttle_pct, speed_kmh: used as-is (low cross-vehicle fragility)

Applied uniformly to every trip in the combined dataset. Deciding which
trips are "trainable normal" vs. held out for validation happens later
(step 5, the train/validation split) — this script doesn't filter by
condition, just computes features generically for everything.
"""

from pathlib import Path

import pandas as pd

# Features that get the rolling-deviation treatment, per the fragility
# table we worked through — coolant/rpm vary a lot by vehicle
# (thermostat setpoint, idle speed, gearing), speed is already a
# comparable physical unit across vehicles.
#
# throttle_pct deliberately excluded: investigation showed KIT's
# Absolute Throttle Position reading is pinned at one value (83.5%)
# for 86% of all rows dataset-wide, with ~zero correlation to RPM/speed
# — essentially dead signal, a known drive-by-wire quirk (physical
# throttle-plate angle vs. driver pedal input). pedal_d_pct is the
# genuinely alive signal in KIT, but our own OBD2Lib firmware doesn't
# collect pedal position yet (only throttle_pct, via CORE_PIDS) — so
# training on pedal_d_pct now would produce a model we could never
# actually score our own vehicle's data against. Revisit once pedal
# position is added to OBD2Lib (flagged alongside the fuel-level
# addition, architecture.md §3.12) — will need this script re-run
# against the updated feature set, cheap to do, not done as part of
# this decision.
DEVIATION_FEATURES = ["coolant_temp_c", "rpm"]
RAW_FEATURES = ["speed_kmh"]

ROLLING_WINDOW = "60s"


def add_deviation_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each trip independently: compute a trailing 60s rolling median
    per deviation feature, subtract it from the raw value, and record
    seconds-since-trip-start (used afterward to trim the cold-start
    window where a full 60s of history doesn't exist yet).

    pandas' time-offset rolling window is causal by default (window
    covers [t-60s, t], never future rows) — this matters because it's
    what lets the exact same transform be reused later to score live
    or newly-collected data, not just this fixed historical dataset.
    """

    def process_one_trip(trip_df: pd.DataFrame) -> pd.DataFrame:
        trip_df = trip_df.sort_values("timestamp").copy()

        rolling_medians = trip_df.rolling(ROLLING_WINDOW, on="timestamp")[
            DEVIATION_FEATURES
        ].median()

        for col in DEVIATION_FEATURES:
            trip_df[f"{col}_dev"] = trip_df[col] - rolling_medians[col]

        trip_start = trip_df["timestamp"].iloc[0]
        trip_df["seconds_since_start"] = (
            trip_df["timestamp"] - trip_start
        ).dt.total_seconds()

        return trip_df

    # Explicit loop rather than groupby(...).apply(...): pandas 2.2+
    # silently excludes the grouping column (trip_id) from what gets
    # passed into an apply'd function by default (a deprecation, easy
    # to miss since it only shows as a warning, not an error) — this
    # bit us, trip_id vanished from the output. Looping over groupby's
    # own (trip_id, sub_df) pairs sidesteps that entirely: trip_df
    # here is a plain slice that still has every original column,
    # trip_id included, regardless of pandas version.
    trip_results = [process_one_trip(trip_df) for _, trip_df in df.groupby("trip_id")]
    return pd.concat(trip_results, ignore_index=True)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = add_deviation_features(df)

    # Drop the cold-start window per trip: rows before a full 60s of
    # rolling history exists yet. Chosen over an expanding-window
    # fallback deliberately — sidesteps the ambiguous "is this
    # deviation real or just not-enough-data-yet" case entirely rather
    # than papering over it with a partial-window median.
    before = len(df)
    df = df[df["seconds_since_start"] >= 60].copy()
    dropped = before - len(df)
    print(f"Dropped {dropped:,} rows in the first 60s of each trip "
          f"({before:,} -> {len(df):,})")

    feature_cols = [f"{c}_dev" for c in DEVIATION_FEATURES] + RAW_FEATURES

    # Any residual NaNs (e.g. from the original startup-fill gaps, if
    # they happened to fall after the 60s mark) get dropped explicitly
    # and counted, rather than silently passed through to the model.
    before = len(df)
    df = df.dropna(subset=feature_cols).copy()
    dropped = before - len(df)
    if dropped:
        print(f"Dropped {dropped:,} additional rows with residual NaNs "
              f"in feature columns")

    return df, feature_cols


if __name__ == "__main__":
    SCRIPT_DIR = Path(__file__).resolve().parent
    ANALYTICS_DIR = SCRIPT_DIR.parent

    in_path = ANALYTICS_DIR / "dataset/processed/kit_combined.parquet"
    out_path = ANALYTICS_DIR / "dataset/processed/kit_features.parquet"

    print(f"Loading: {in_path}")
    df = pd.read_parquet(in_path)
    print(f"Loaded {len(df):,} rows across {df['trip_id'].nunique()} trips\n")

    df, feature_cols = build_features(df)

    print(f"\nFeature columns: {feature_cols}")
    print("\nFeature summary:")
    print(df[feature_cols].describe())

    print(f"\nRemaining rows: {len(df):,} across {df['trip_id'].nunique()} trips")

    df.to_parquet(out_path, index=False)
    print(f"\nSaved to: {out_path}")