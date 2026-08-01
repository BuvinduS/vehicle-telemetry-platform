"""
ved_loader.py — Load and clean raw VED (Vehicle Energy Dataset) weekly CSVs.

Mirrors the role of kit_loader.py in the KIT-based pipeline, but the actual
cleaning steps are different because VED's data-quality problems are
different from KIT's:

- No encoding issue (VED headers/rows are pure ASCII; confirmed via
  byte-level inspection before writing this script — nothing to fix here).
- Two static metadata files use inconsistent column names for the same
  concept ("Vehicle Type" in VED_Static_Data_ICE&HEV.xlsx vs. "EngineType"
  in VED_Static_Data_PHEV&EV.xlsx) — normalized here.
- Per-vehicle PID-support gaps: Absolute Load[%] is bimodal per vehicle
  (a given vehicle reports it ~always or ~never, almost nothing in
  between) — confirmed via full-dataset inspection, not assumed. Vehicles
  that don't report it are excluded from that engine type's pool rather
  than imputed across, same principle as OBD2Lib's checkCorePIDSupport().
- Native sampling is irregular and already close to ~1Hz (median trip
  effective rate ~1.1 rows/sec) — NOT KIT's ~10Hz forward-filled logging.
  This script does not resample; that's feature_engineering.py's job,
  and it uses time-based resampling rather than KIT's row-based approach
  precisely because the native rate here isn't a clean fixed interval.

Scope: this project only builds ICE and HEV model variants (per kickoff
decision) — PHEV/EV rows are dropped entirely, not carried through.

Anchors all paths to this file's own directory, never the CWD (lesson
carried over from the KIT chat).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

# Columns actually used downstream. Fuel Rate[L/hr] is deliberately excluded
# even though it exists in the source — confirmed ~100% null across every
# powertrain type in this dataset, not just some; not worth carrying.
KEEP_COLS = [
    "VehId",
    "Trip",
    "DayNum",
    "Timestamp(ms)",
    "Vehicle Speed[km/h]",
    "Engine RPM[RPM]",
    "Absolute Load[%]",
]

RENAME = {
    "Vehicle Speed[km/h]": "speed_kmh",
    "Engine RPM[RPM]": "rpm",
    "Absolute Load[%]": "engine_load_pct",
}

# Per-vehicle PID-support threshold: a vehicle is considered to genuinely
# support Absolute Load only if it's null on fewer than this fraction of
# its own rows. Confirmed bimodal (vehicles cluster near 0.0 or near 1.0,
# essentially nothing in between) — this threshold is deliberately loose
# (0.3) since the real population is bimodal, not a judgment call being
# smuggled in as a precise-looking number.
LOAD_SUPPORT_NULL_THRESHOLD = 0.3

# Reference date for DayNum -> wall-clock conversion, per VED's README:
# "DayNum 1 = Nov 1st, 2017, 00:00:00". DayNum is 1-indexed and fractional
# (DayNum 1.5 = Nov 1st, 2017, 12:00:00), so the offset from the epoch
# below is (DayNum - 1) days.
VED_EPOCH = pd.Timestamp("2017-11-01T00:00:00")


def load_static_metadata(static_dir: Path) -> pd.DataFrame:
    """Load and normalize both static vehicle-metadata files.

    Returns a DataFrame indexed by VehId with a single `engine_type` column
    ("ICE" / "HEV" / "PHEV" / "EV"). The two source files use different
    column names for this ("Vehicle Type" vs "EngineType") — normalized
    here rather than left as a footgun for whoever reads this next.
    """
    ice_hev = pd.read_excel(static_dir / "VED_Static_Data_ICE&HEV.xlsx")
    phev_ev = pd.read_excel(static_dir / "VED_Static_Data_PHEV&EV.xlsx")

    ice_hev = ice_hev.rename(columns={"Vehicle Type": "engine_type"})
    phev_ev = phev_ev.rename(columns={"EngineType": "engine_type"})

    static = pd.concat(
        [ice_hev[["VehId", "engine_type"]], phev_ev[["VehId", "engine_type"]]],
        ignore_index=True,
    )

    dupes = static["VehId"].duplicated()
    if dupes.any():
        raise ValueError(
            f"VehId appears in both static files: {static.loc[dupes, 'VehId'].tolist()}"
        )

    return static.set_index("VehId")["engine_type"]


def compute_load_support(dynamic_dir: Path, veh_engine_type: pd.Series) -> pd.Series:
    """Determine, per vehicle, whether it genuinely reports Absolute Load.

    Streams through all weekly files accumulating null/row counts per
    VehId rather than loading everything into memory at once — this
    dataset is ~22M rows / ~3GB uncompressed, no reason to hold it all
    in memory just to compute a coverage fraction.
    """
    null_counts: dict[int, int] = {}
    row_counts: dict[int, int] = {}

    files = sorted(dynamic_dir.glob("VED_*_week.csv"))
    if not files:
        raise FileNotFoundError(f"No VED_*_week.csv files found in {dynamic_dir}")

    for f in files:
        df = pd.read_csv(f, usecols=["VehId", "Absolute Load[%]"])
        for veh_id, grp in df.groupby("VehId"):
            null_counts[veh_id] = null_counts.get(veh_id, 0) + grp["Absolute Load[%]"].isnull().sum()
            row_counts[veh_id] = row_counts.get(veh_id, 0) + len(grp)

    null_frac = pd.Series(
        {veh: null_counts[veh] / row_counts[veh] for veh in row_counts}
    )
    return null_frac


def load_and_clean(dynamic_dir: Path, static_dir: Path, cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("Loading static metadata...", file=sys.stderr)
    veh_engine_type = load_static_metadata(static_dir)

    load_support_cache = cache_dir / "load_null_frac_per_vehicle.csv"
    if load_support_cache.exists():
        print(f"Reusing cached per-vehicle load-null-frac: {load_support_cache}", file=sys.stderr)
        load_null_frac = pd.read_csv(load_support_cache, index_col=0)["load_null_frac"]
    else:
        print("Computing per-vehicle Absolute Load support (one pass over all files)...", file=sys.stderr)
        load_null_frac = compute_load_support(dynamic_dir, veh_engine_type)
        load_null_frac.rename("load_null_frac").to_csv(load_support_cache)

    supports_load = load_null_frac < LOAD_SUPPORT_NULL_THRESHOLD
    excluded_vehicles = set(load_null_frac[~supports_load].index)
    print(
        f"{len(excluded_vehicles)} of {len(load_null_frac)} vehicles excluded "
        f"for not reporting Absolute Load (null frac >= {LOAD_SUPPORT_NULL_THRESHOLD})",
        file=sys.stderr,
    )

    files = sorted(dynamic_dir.glob("VED_*_week.csv"))

    ice_frames = []
    hev_frames = []

    for f in files:
        df = pd.read_csv(f, usecols=KEEP_COLS)
        df = df[~df["VehId"].isin(excluded_vehicles)]
        df["engine_type"] = df["VehId"].map(veh_engine_type)
        df = df[df["engine_type"].isin(["ICE", "HEV"])]
        if df.empty:
            continue

        # Real wall-clock timestamp. DayNum is 1-indexed and fractional
        # (paper/README: DayNum 1 = Nov 1 2017 00:00:00); Timestamp(ms) is
        # milliseconds elapsed since the *trip's* own start, not since
        # DayNum's reference point, so it's added as a within-trip offset
        # on top of the DayNum-derived trip-start time. This matches how
        # the raw data actually behaves (Timestamp(ms) resets to a small
        # value at the start of every new Trip) rather than treating it as
        # a single continuous clock across the whole file.
        df["trip_start_time"] = VED_EPOCH + pd.to_timedelta(df["DayNum"] - 1, unit="D")
        df["time"] = df["trip_start_time"] + pd.to_timedelta(df["Timestamp(ms)"], unit="ms")

        df = df.rename(columns=RENAME)
        df = df[["VehId", "Trip", "time", "speed_kmh", "rpm", "engine_load_pct", "engine_type"]]

        ice_frames.append(df[df.engine_type == "ICE"].drop(columns="engine_type"))
        hev_frames.append(df[df.engine_type == "HEV"].drop(columns="engine_type"))

        print(f"  processed {f.name}", file=sys.stderr)

    ice_df = pd.concat(ice_frames, ignore_index=True)
    hev_df = pd.concat(hev_frames, ignore_index=True)

    ice_df.to_parquet(cache_dir / "ved_ice_clean.parquet", index=False)
    hev_df.to_parquet(cache_dir / "ved_hev_clean.parquet", index=False)

    print(f"ICE: {len(ice_df):,} rows, {ice_df.VehId.nunique()} vehicles -> ved_ice_clean.parquet", file=sys.stderr)
    print(f"HEV: {len(hev_df):,} rows, {hev_df.VehId.nunique()} vehicles -> ved_hev_clean.parquet", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic-dir", type=Path, required=True, help="Directory of extracted VED_*_week.csv files")
    parser.add_argument("--static-dir", type=Path, required=True, help="Directory containing the two VED static .xlsx files")
    parser.add_argument("--cache-dir", type=Path, default=HERE / "cache", help="Where to write cleaned parquet output + intermediate caches")
    args = parser.parse_args()

    load_and_clean(args.dynamic_dir, args.static_dir, args.cache_dir)


if __name__ == "__main__":
    main()