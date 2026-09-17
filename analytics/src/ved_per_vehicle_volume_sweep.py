"""
ved_per_vehicle_volume_sweep.py — Phase 1 of the per-vehicle model chat:
"how much of a single vehicle's own history is enough before a
self-trained anomaly-detection model is trustworthy?"

For each vehicle in the sweep-vehicle selection (see
select_sweep_vehicles.py), this script:

  1. Holds out that vehicle's own LAST 20% of trips, chronologically, as
     a fixed test set — used for every training-volume step below, never
     touched during training at any step. Trip-count-based rather than
     calendar-based, because VED logs per-trip with irregular gaps: a
     fixed calendar window (e.g. "last 2 weeks") could land on a
     stretch with zero trips for a sparsely-logged vehicle. This was
     flagged to the person as an assumption, not silently decided.

  2. For each training-volume step (calendar days elapsed since that
     vehicle's own first trip: 1 / 3 / 7 / 14 / 30 / all-remaining,
     per the kickoff prompt's "1 day, 1 week, 1 month..." framing —
     this axis IS calendar-based, deliberately different from the
     trip-count-based test holdout above), trains a fresh Isolation
     Forest on whatever training trips fall within that window, then
     runs the existing fault-injection sweep (ved_synthetic_fault_injection.py,
     reused unmodified) against the fixed held-out test trips.

  3. Produces one row per (vehicle, volume_step, fault_type, std_multiple)
     with detection rate at each reference FPR — the raw material for the
     "detection rate vs. accumulated training volume" curve per vehicle,
     which is what actually answers "how much is enough."

Reuses ved_feature_engineering.process() and ved_synthetic_fault_injection's
sample_fault_windows/inject_fault/run_sweep unmodified — this script only
adds the per-vehicle trip splitting, the calendar-day training cutoffs,
and per-step model fitting (IsolationForest(n_estimators=100,
random_state=42), matching every other model in this project — see
model_details.md §4.1).

Guardrails: some selected vehicles have very little total data (e.g. one
selected HEV vehicle has ~4,600 rows total). This script does NOT
silently produce misleading numbers for a vehicle that can't support the
experiment — a vehicle is skipped entirely (with a clear reason printed)
if it doesn't have enough trips to form a valid test set, and individual
volume steps are skipped (not the whole vehicle) if that step's training
window happens to contain zero trips or nothing survives feature
engineering.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

import ved_feature_engineering as vfe
import ved_synthetic_fault_injection as vsfi

# ---------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------

TEST_TRIP_FRACTION = 0.20   # last 20% of trips, chronologically, held out
MIN_TEST_TRIPS = 3           # below this, the vehicle is skipped entirely
MIN_TRAIN_TRIPS_PER_STEP = 1  # below this, that single step is skipped

DEFAULT_DAY_CUTOFFS = [1, 3, 7, 14, 30]   # + "all" appended automatically
DEVIATION_WINDOW_SECONDS = 30              # rolling-median window for
                                            # rpm_dev/engine_load_pct_dev —
                                            # matches the better-performing
                                            # 30s HEV variant (model_details.md
                                            # §10.3) rather than the original
                                            # 60s default. Override via CLI
                                            # if you want to test 60s too.

N_ESTIMATORS = 100
MODEL_RANDOM_STATE = 42
FAULT_SEED = 42

STD_MULTIPLES = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0]

# --- Per-vehicle fault-window sampling ---
# vsfi.sample_fault_windows() (reused for the original pooled cross-vehicle
# val sets) draws AT MOST ONE window per trip — fine when val has hundreds
# of trips, but a per-vehicle test set here can have as few as 2-4 trips,
# which means as few as 2-4 independent detection "trials" total. A
# detection rate computed from that few trials is dominated by sampling
# noise, not model quality — confirmed directly: several vehicles in the
# first real run showed detection apparently "saturating" at essentially
# zero training days, which traced back to exactly the vehicles with the
# fewest held-out trips, not to genuinely fast learning.
#
# Fix, scoped locally to this script rather than modifying
# ved_synthetic_fault_injection.py (which is correctly tuned for its own,
# different use case): draw several non-overlapping windows per trip
# instead of one, and refuse to report a detection rate at all below a
# minimum total window count.
MAX_WINDOWS_PER_TRIP = 5     # non-overlapping — caps one long trip from
                              # dominating a vehicle's whole sample
MIN_TOTAL_WINDOWS = 15       # below this, the vehicle is skipped entirely
                              # (not just flagged) — same "don't produce a
                              # number that looks real but isn't" principle
                              # as the vehicle-level skips already in place

# ---------------------------------------------------------------------


def load_vehicle(cache_dir: Path, pool: str, vehicle_id: int) -> pd.DataFrame:
    path = cache_dir / f"ved_{pool.lower()}_clean.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"Cleaned parquet not found at '{path}' — check --cache-dir, "
            f"or that ved_loader.py has been run for this pool."
        )
    df = pd.read_parquet(path)
    df = df[df["VehId"] == vehicle_id].copy()
    if df.empty:
        raise ValueError(f"VehId {vehicle_id} not found in '{path}'.")
    return df


def trip_boundaries(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (VehId, Trip): start_time, end_time, n_rows. Sorted by start_time."""
    g = df.groupby(["VehId", "Trip"])["time"]
    bounds = g.agg(start_time="min", end_time="max", n_rows="count").reset_index()
    return bounds.sort_values("start_time").reset_index(drop=True)


def split_test_trips(bounds: pd.DataFrame, test_fraction: float, min_test_trips: int):
    """Last `test_fraction` of trips, chronologically, held out as the fixed
    test set for every training-volume step of this vehicle.

    Returns (train_trip_ids: set, test_trip_ids: set, first_trip_time,
    ok: bool, reason: str|None).
    """
    n_trips = len(bounds)
    n_test = max(min_test_trips, int(np.ceil(n_trips * test_fraction)))

    if n_trips - n_test < 1:
        return None, None, None, False, (
            f"only {n_trips} total trips — cannot hold out {n_test} for "
            f"test (min_test_trips={min_test_trips}) and still have any "
            f"training trips left."
        )

    test_bounds = bounds.iloc[-n_test:]
    train_bounds = bounds.iloc[:-n_test]

    test_ids = set(zip(test_bounds["VehId"], test_bounds["Trip"]))
    train_ids = set(zip(train_bounds["VehId"], train_bounds["Trip"]))
    first_trip_time = bounds["start_time"].min()

    return train_ids, test_ids, first_trip_time, True, None


def trips_within_days(bounds: pd.DataFrame, trip_id_pool: set, first_trip_time, days) -> set:
    """Subset of trip_id_pool whose start_time falls within `days` of
    first_trip_time. `days=None` means "all of trip_id_pool" (the
    all-remaining-training-data step)."""
    if days is None:
        return trip_id_pool

    cutoff = first_trip_time + pd.Timedelta(days=days)
    eligible = bounds[
        (bounds["start_time"] <= cutoff)
        & bounds.apply(lambda r: (r["VehId"], r["Trip"]) in trip_id_pool, axis=1)
    ]
    return set(zip(eligible["VehId"], eligible["Trip"]))


def subset_by_trip_ids(df: pd.DataFrame, trip_ids: set) -> pd.DataFrame:
    mask = df.apply(lambda r: (r["VehId"], r["Trip"]) in trip_ids, axis=1)
    return df[mask].copy()


def sample_fault_windows_dense(df: pd.DataFrame, max_per_trip: int, seed: int) -> list:
    """Draw up to `max_per_trip` non-overlapping vsfi.WINDOW_SECONDS-length
    windows from each (VehId, Trip) group — a locally-scoped replacement for
    vsfi.sample_fault_windows's one-window-per-trip behavior, needed because
    a single vehicle's held-out test set has far fewer trips than the pooled
    cross-vehicle val sets that function was designed for. See CONFIG block
    above for the full reasoning.

    Windows are carved as sequential, non-overlapping chunks starting from
    each trip's own first surviving row, then up to `max_per_trip` of the
    resulting chunks are kept (all of them if fewer exist), chosen via a
    seeded shuffle so which chunks are kept is reproducible. Same per-window
    validity checks as vsfi.sample_fault_windows (no nulls in FEATURE_COLS,
    at least 3 rows).
    """
    rng = np.random.default_rng(seed)
    windows = []

    for (veh, trip), sub in df.groupby(["VehId", "Trip"]):
        sub = sub.sort_values("time")
        start = sub["time"].iloc[0]
        end = sub["time"].iloc[-1]
        span_s = (end - start).total_seconds()

        n_chunks = int(span_s // vsfi.WINDOW_SECONDS)
        if n_chunks < 1:
            continue

        chunk_indices = list(range(n_chunks))
        rng.shuffle(chunk_indices)

        for ci in chunk_indices[:max_per_trip]:
            w_start = start + pd.Timedelta(seconds=ci * vsfi.WINDOW_SECONDS)
            w_end = w_start + pd.Timedelta(seconds=vsfi.WINDOW_SECONDS)
            window = sub[(sub["time"] >= w_start) & (sub["time"] < w_end)]
            if window[vsfi.FEATURE_COLS].isnull().any().any():
                continue
            if len(window) < 3:
                continue
            windows.append(window)

    return windows


def run_multi_window_sweep(
    model,
    val_df_for_thresholds: pd.DataFrame,
    windows: list,
    fault_type: str,
    std_multiples: list,
    feature_std: float,
) -> pd.DataFrame:
    """Same logic as vsfi.run_sweep, but takes a pre-sampled window list
    directly instead of calling vsfi.sample_fault_windows internally — lets
    this script supply the denser per-vehicle sample from
    sample_fault_windows_dense() above while reusing everything else
    (reference-threshold computation, fault injection, scoring) unmodified
    from ved_synthetic_fault_injection.py."""
    val_scores_all = model.decision_function(
        val_df_for_thresholds[vsfi.FEATURE_COLS].dropna().to_numpy()
    )
    ref_thresholds = {
        fpr: float(np.percentile(val_scores_all, fpr * 100))
        for fpr in vsfi.REFERENCE_FPR_TARGETS
    }

    rows = []
    for mult in std_multiples:
        magnitude = mult * feature_std
        detections = {fpr: 0 for fpr in vsfi.REFERENCE_FPR_TARGETS}
        total = 0
        for window in windows:
            faulted = vsfi.inject_fault(window, fault_type, magnitude)
            scores = model.decision_function(faulted[vsfi.FEATURE_COLS].to_numpy())
            for fpr, thresh in ref_thresholds.items():
                detections[fpr] += int((scores < thresh).any())
            total += 1

        row = {"std_multiple": mult, "magnitude": magnitude, "n_windows": total}
        for fpr in vsfi.REFERENCE_FPR_TARGETS:
            row[f"detect_rate_at_{int(fpr*100)}pct_fpr"] = (
                detections[fpr] / total if total else float("nan")
            )
        rows.append(row)

    return pd.DataFrame(rows)


def run_vehicle(
    cache_dir: Path,
    pool: str,
    vehicle_id: int,
    day_cutoffs: list,
    window_seconds: int,
) -> pd.DataFrame | None:
    print(f"\n=== {pool} vehicle {vehicle_id} ===", file=sys.stderr)

    raw = load_vehicle(cache_dir, pool, vehicle_id)
    bounds = trip_boundaries(raw)
    print(f"  {len(bounds)} total trips, {len(raw)} total rows", file=sys.stderr)

    train_ids, test_ids, first_trip_time, ok, reason = split_test_trips(
        bounds, TEST_TRIP_FRACTION, MIN_TEST_TRIPS
    )
    if not ok:
        print(f"  SKIPPING vehicle: {reason}", file=sys.stderr)
        return None
    print(f"  train pool: {len(train_ids)} trips, held-out test: {len(test_ids)} trips", file=sys.stderr)

    # Feature-engineer the fixed test set once — reused unchanged across
    # every training-volume step, so the comparison is apples-to-apples.
    test_raw = subset_by_trip_ids(raw, test_ids)
    try:
        test_features = vfe.process(test_raw, window_seconds)
    except ValueError as e:
        print(f"  SKIPPING vehicle: test set produced no usable features ({e})", file=sys.stderr)
        return None

    if test_features.empty:
        print(f"  SKIPPING vehicle: test set empty after feature engineering", file=sys.stderr)
        return None
    print(f"  test set: {len(test_features)} rows after feature engineering", file=sys.stderr)

    # Draw the dense multi-window sample from the fixed test set ONCE —
    # independent of training volume, reused unchanged across every step
    # below, same fairness reasoning as test_features itself.
    test_windows = sample_fault_windows_dense(test_features, MAX_WINDOWS_PER_TRIP, FAULT_SEED)
    if len(test_windows) < MIN_TOTAL_WINDOWS:
        print(
            f"  SKIPPING vehicle: only {len(test_windows)} fault-injection windows "
            f"available from the held-out test trips (need >= {MIN_TOTAL_WINDOWS}) — "
            f"too few independent trials to report a meaningful detection rate, "
            f"regardless of training volume.",
            file=sys.stderr,
        )
        return None
    print(f"  {len(test_windows)} fault-injection windows sampled from test set "
          f"(fixed, reused across all training-volume steps)", file=sys.stderr)

    all_steps = list(day_cutoffs) + [None]  # None == "all remaining training trips"
    results = []

    for days in all_steps:
        step_label = "all" if days is None else str(days)
        step_trip_ids = trips_within_days(bounds, train_ids, first_trip_time, days)

        if len(step_trip_ids) < MIN_TRAIN_TRIPS_PER_STEP:
            print(f"  [step={step_label}d] skipped — 0 training trips in this window", file=sys.stderr)
            continue

        step_raw = subset_by_trip_ids(raw, step_trip_ids)
        try:
            step_features = vfe.process(step_raw, window_seconds)
        except ValueError:
            print(f"  [step={step_label}d] skipped — no trips survived feature engineering "
                  f"(all shorter than {window_seconds}s)", file=sys.stderr)
            continue

        step_features = step_features.dropna(subset=vsfi.FEATURE_COLS)
        if len(step_features) < 10:
            print(f"  [step={step_label}d] skipped — only {len(step_features)} usable training rows", file=sys.stderr)
            continue

        step_bounds = bounds[bounds.apply(lambda r: (r["VehId"], r["Trip"]) in step_trip_ids, axis=1)]
        actual_span_days = (step_bounds["start_time"].max() - first_trip_time).total_seconds() / 86400

        model = IsolationForest(n_estimators=N_ESTIMATORS, random_state=MODEL_RANDOM_STATE)
        model.fit(step_features[vsfi.FEATURE_COLS].to_numpy())

        print(f"  [step={step_label}d] {len(step_trip_ids)} train trips, "
              f"{len(step_features)} train rows, actual span {actual_span_days:.1f}d", file=sys.stderr)

        for fault_type, target_col in vsfi.FAULT_TARGET_COL.items():
            feature_std = step_features[target_col].std()
            if not np.isfinite(feature_std) or feature_std == 0:
                print(f"    [{fault_type}] skipped — degenerate std ({feature_std})", file=sys.stderr)
                continue

            sweep = run_multi_window_sweep(
                model, test_features, test_windows, fault_type, STD_MULTIPLES, feature_std,
            )
            sweep["vehicle_id"] = vehicle_id
            sweep["powertrain"] = pool
            sweep["day_cutoff"] = step_label
            sweep["n_train_trips"] = len(step_trip_ids)
            sweep["n_train_rows"] = len(step_features)
            sweep["actual_train_span_days"] = round(actual_span_days, 2)
            sweep["fault_type"] = fault_type
            results.append(sweep)

    if not results:
        print(f"  No usable steps for vehicle {vehicle_id} — nothing written.", file=sys.stderr)
        return None

    return pd.concat(results, ignore_index=True)


def main():
    global MAX_WINDOWS_PER_TRIP, MIN_TOTAL_WINDOWS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True,
                         help="Directory containing ved_ice_clean.parquet / ved_hev_clean.parquet")
    parser.add_argument("--selection-csv", type=Path, required=True,
                         help="Output of select_sweep_vehicles.py")
    parser.add_argument("--day-cutoffs", type=int, nargs="+", default=DEFAULT_DAY_CUTOFFS)
    parser.add_argument("--window-seconds", type=int, default=DEVIATION_WINDOW_SECONDS,
                         help="Rolling-deviation window for rpm_dev/engine_load_pct_dev")
    parser.add_argument("--max-windows-per-trip", type=int, default=MAX_WINDOWS_PER_TRIP,
                         help="Max non-overlapping fault-injection windows drawn per test trip")
    parser.add_argument("--min-total-windows", type=int, default=MIN_TOTAL_WINDOWS,
                         help="Minimum total fault windows required to report a vehicle's results")
    parser.add_argument("--output-csv", type=Path, required=True)

    args = parser.parse_args()
    MAX_WINDOWS_PER_TRIP = args.max_windows_per_trip
    MIN_TOTAL_WINDOWS = args.min_total_windows

    selection = pd.read_csv(args.selection_csv)
    required = {"vehicle_id", "powertrain"}
    missing = required - set(selection.columns)
    assert not missing, f"selection CSV missing columns: {missing} (found: {list(selection.columns)})"

    all_results = []
    for _, row in selection.iterrows():
        result = run_vehicle(
            args.cache_dir, row["powertrain"], row["vehicle_id"],
            args.day_cutoffs, args.window_seconds,
        )
        if result is not None:
            all_results.append(result)

    if not all_results:
        print("\nNo vehicles produced usable results — nothing written.", file=sys.stderr)
        sys.exit(1)

    combined = pd.concat(all_results, ignore_index=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(args.output_csv, index=False)

    print(f"\nWrote {len(combined)} rows ({combined['vehicle_id'].nunique()} vehicles) "
          f"to '{args.output_csv}'", file=sys.stderr)
    print(
        "\nNext step: plot detect_rate_at_2pct_fpr (or 5/10pct) vs. "
        "actual_train_span_days per vehicle/fault_type at a fixed "
        "std_multiple (e.g. 3.0, which fully saturated in the earlier "
        "KIT/VED work) to read off where each vehicle's curve stabilizes.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()