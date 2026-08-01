"""
ved_feature_engineering.py — compute rolling-deviation features per trip
for the VED-derived ICE/HEV cleaned datasets (output of ved_loader.py).

Same conceptual approach as the KIT pipeline's feature_engineering.py
(trailing rolling-median deviation, strictly causal, per-trip, cold-start
window trimmed) but a DIFFERENT mechanical implementation, because VED's
sampling characteristics are genuinely different from KIT's:

- KIT: forward-filled at a fixed ~10Hz, so a row-based rolling window
  (fixed row count) corresponds to a fixed and known time span.
- VED: irregular native sampling, already close to ~1Hz on average but
  NOT a fixed interval (confirmed during inspection: median trip
  effective rate ~1.1 rows/sec, individual timestamp deltas ranging
  from 100ms to multi-second gaps). A row-based rolling window here
  would correspond to a different, unpredictable time span from one
  trip (or even one stretch of a trip) to the next. This script uses
  pandas' TIME-based rolling window (`.rolling("60s")` on a
  DatetimeIndex) instead, which correctly handles irregular spacing —
  the window is always "the last 60 seconds of wall-clock time,"
  regardless of how many rows happen to fall inside it.

Features produced (mirrors the KIT model's 3-feature shape, with
`engine_load_pct_dev` standing in for KIT's `coolant_temp_c_dev`, since
VED has no coolant column at all — see architecture.md / model_details.md
for the full trade-off discussion):

- `rpm_dev`            — rpm minus its own trailing 60s rolling median
- `engine_load_pct_dev`— engine_load_pct minus its own trailing 60s
                          rolling median
- `speed_kmh`           — raw value, unchanged (same as the KIT model —
                          km/h is directly comparable, low cross-vehicle
                          fragility, doesn't need a deviation transform)

Per the "pandas 2.2+ groupby().apply() silently drops the grouping
column" lesson from the KIT chat: this script loops over `groupby()`'s
own (key, sub_df) pairs explicitly rather than using `.apply()`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

ROLLING_WINDOW = "60s"
# Minimum wall-clock span of real history required before a row's
# deviation is considered valid — matches the window length itself.
# Rows before this point in a trip are dropped, same "avoid an ambiguous
# partial-window case entirely" reasoning as the KIT chat's cold-start
# trim (feature_engineering.py), just re-derived here for a time-based
# window rather than a row-count-based one.
MIN_TRIP_SECONDS = 60


def compute_trip_features(trip_df: pd.DataFrame) -> pd.DataFrame:
    """Compute rolling-deviation features for a single (VehId, Trip) group.

    Assumes `trip_df` contains exactly one vehicle/trip's rows. Returns a
    new DataFrame with `rpm_dev` / `engine_load_pct_dev` added and the
    cold-start window trimmed, or an empty DataFrame if the trip is
    shorter than MIN_TRIP_SECONDS entirely.
    """
    trip_df = trip_df.sort_values("time")

    span_s = (trip_df["time"].iloc[-1] - trip_df["time"].iloc[0]).total_seconds()
    if span_s < MIN_TRIP_SECONDS:
        return trip_df.iloc[0:0]

    indexed = trip_df.set_index("time")

    rolling_rpm_median = indexed["rpm"].rolling(ROLLING_WINDOW).median()
    rolling_load_median = indexed["engine_load_pct"].rolling(ROLLING_WINDOW).median()

    indexed["rpm_dev"] = indexed["rpm"] - rolling_rpm_median
    indexed["engine_load_pct_dev"] = indexed["engine_load_pct"] - rolling_load_median

    out = indexed.reset_index()

    cutoff = out["time"].iloc[0] + pd.Timedelta(seconds=MIN_TRIP_SECONDS)
    out = out[out["time"] >= cutoff]

    return out


def process(df: pd.DataFrame) -> pd.DataFrame:
    """Apply compute_trip_features to every (VehId, Trip) group.

    Explicit loop over groupby's own (key, sub_df) pairs rather than
    `.apply()` — pandas 2.2+ silently drops the grouping columns from
    what's passed into an applied function, which bit the KIT chat once
    already (see lessons-learned.md).
    """
    results = []
    n_groups = df.groupby(["VehId", "Trip"]).ngroups
    print(f"Processing {n_groups} (VehId, Trip) groups...", file=sys.stderr)

    for i, ((veh_id, trip), sub_df) in enumerate(df.groupby(["VehId", "Trip"])):
        featured = compute_trip_features(sub_df)
        if not featured.empty:
            results.append(featured)
        if i % 2000 == 0:
            print(f"  {i}/{n_groups} groups", file=sys.stderr)

    if not results:
        raise ValueError("No trips survived feature engineering — check MIN_TRIP_SECONDS / input data")

    out = pd.concat(results, ignore_index=True)
    return out[["VehId", "Trip", "time", "speed_kmh", "rpm_dev", "engine_load_pct_dev"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Path to ved_ice_clean.parquet or ved_hev_clean.parquet")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the featured parquet")
    args = parser.parse_args()

    print(f"Loading {args.input}...", file=sys.stderr)
    df = pd.read_parquet(args.input)
    print(f"  {len(df):,} rows, {df.VehId.nunique()} vehicles, {df.groupby(['VehId','Trip']).ngroups} trips", file=sys.stderr)

    featured = process(df)

    n_dropped_trips = df.groupby(["VehId", "Trip"]).ngroups - featured.groupby(["VehId", "Trip"]).ngroups
    print(
        f"Done: {len(featured):,} rows, {featured.groupby(['VehId','Trip']).ngroups} trips retained "
        f"({n_dropped_trips} trips dropped for being under {MIN_TRIP_SECONDS}s)",
        file=sys.stderr,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    featured.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()