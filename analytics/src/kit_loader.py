"""
kit_loader.py — loads ONE KIT OBD-II trip CSV into a clean DataFrame.

Step 1 of the anomaly-detection pipeline: prove the loader works on a
single file before scaling to all 81. See architecture.md §3.13.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Maps the KIT dataset's verbose column headers to our own schema's
# naming convention (rpm, coolant_temp_c, etc.) — same style as
# mqtt-topics.md's payload field names, so downstream code reads the
# same field names regardless of which dataset it came from.
COLUMN_RENAME = {
    "Time": "time_str",
    "Engine Coolant Temperature [°C]": "coolant_temp_c",
    "Intake Manifold Absolute Pressure [kPa]": "map_kpa",
    "Engine RPM [RPM]": "rpm",
    "Vehicle Speed Sensor [km/h]": "speed_kmh",
    "Intake Air Temperature [°C]": "intake_air_temp_c",
    "Air Flow Rate from Mass Flow Sensor [g/s]": "maf_gs",
    "Absolute Throttle Position [%]": "throttle_pct",
    "Ambient Air Temperature [°C]": "ambient_temp_c",
    "Accelerator Pedal Position D [%]": "pedal_d_pct",
    "Accelerator Pedal Position E [%]": "pedal_e_pct",
}

# Filenames look like: 2018-03-21_Seat_Leon_KA_RT_Normal.csv
FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")

# The last underscore-separated token before ".csv" is KIT's condition
# label. Most are "Normal"/"Frei"/"Stau" (ordinary driving); a handful
# are one-off special situations KIT itself flags separately
# (Vollbremsung, Glatteis, Beschleunigung, Messfehler) — worth keeping
# as a column now so step 2 (feature engineering) can filter on it
# without re-parsing filenames.
CONDITION_RE = re.compile(r"_([A-Za-z]+)$")

# KIT's labels are German. Translated here so nothing downstream has
# to carry German terms — source_file still preserves the original
# filename if anyone needs to trace a row back to KIT's own naming.
CONDITION_TRANSLATION = {
    "Normal": "normal",
    "Frei": "free_flow",       # free-flowing traffic
    "Stau": "traffic_jam",
    "Vollbremsung": "hard_braking",
    "Glatteis": "black_ice",
    "Beschleunigung": "acceleration_test",
    "Messfehler": "measurement_error",
}


def _read_text_fixing_mojibake(path: Path) -> str:
    """
    39 of the 81 KIT files have the header's '°C' double-encoded —
    the bytes are UTF-8 that itself encodes what should have been a
    single '°' character, one encoding pass too many upstream at KIT's
    end. Confirmed at the raw-byte level during initial inspection
    (not a read-time artifact on our side).

    Fix: decode as UTF-8 (gives the mojibake text 'Â°C'), then
    round-trip it — re-encode as latin-1 (byte-for-byte, since latin-1
    maps 1 byte -> 1 codepoint with no translation) and decode as
    UTF-8 again. That undoes exactly one extra layer of encoding.
    Files that were only encoded once pass through this check
    untouched, since the mojibake pattern won't be present.
    """
    raw = path.read_bytes()
    first_line = raw.split(b"\n", 1)[0]
    if b"\xc3\x82\xc2\xb0C" in first_line:
        text = raw.decode("utf-8")
        return text.encode("latin1").decode("utf-8")
    return raw.decode("utf-8")


def load_trip(path: Path) -> pd.DataFrame:
    """Load and clean a single KIT trip CSV."""
    text = _read_text_fixing_mojibake(path)

    from io import StringIO

    df = pd.read_csv(StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=COLUMN_RENAME)

    # The 'Time' column is HH:MM:SS.mmm only — no date. We pull the
    # date out of the filename instead. A trip could theoretically
    # cross midnight; we detect that by watching for the clock going
    # backwards partway through the file and rolling the date forward
    # when it does, rather than assuming every trip finishes same-day.
    match = FILENAME_DATE_RE.match(path.name)
    if not match:
        raise ValueError(f"Filename doesn't match expected date pattern: {path.name}")
    base_date = datetime.strptime(match.group(1), "%Y-%m-%d")

    times = pd.to_datetime(df["time_str"], format="%H:%M:%S.%f").dt.time
    timestamps = []
    day_offset = 0
    prev_t = None
    for t in times:
        if prev_t is not None and t < prev_t:
            day_offset += 1
        timestamps.append(datetime.combine(base_date + timedelta(days=day_offset), t))
        prev_t = t
    df["timestamp"] = timestamps
    df = df.drop(columns=["time_str"])

    df["source_file"] = path.name

    stem = path.stem  # filename without ".csv"
    condition_match = CONDITION_RE.search(stem)
    raw_condition = condition_match.group(1) if condition_match else "unknown"
    df["condition"] = CONDITION_TRANSLATION.get(raw_condition, raw_condition.lower())

    return df


def load_all_trips(dataset_dir: Path) -> pd.DataFrame:
    """
    Load every trip CSV in dataset_dir and combine into one DataFrame.

    Each trip gets a stable trip_id (0, 1, 2, ...) assigned by sorted
    filename order — sorted so re-running this produces the same IDs
    every time, rather than depending on filesystem listing order
    (which isn't guaranteed stable across OSes/runs). This is what
    step 3 (train/validation split) will split on, so a trip's rows
    always stay together on one side of the split rather than leaking
    a few rows of the same trip into both.
    """
    files = sorted(dataset_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {dataset_dir}")

    trip_dfs = []
    for trip_id, path in enumerate(files):
        df = load_trip(path)
        df["trip_id"] = trip_id
        trip_dfs.append(df)

    return pd.concat(trip_dfs, ignore_index=True)


if __name__ == "__main__":
    # Anchor to this script's own location, not the current working
    # directory. The bug this fixes: a relative path resolves against
    # wherever the terminal's cwd happens to be when you run the
    # script, which silently produces a wrong nested path (e.g.
    # analytics/analytics/...) if you run it from a different folder
    # than whoever wrote the script assumed. __file__ always points at
    # this script's real location on disk regardless of cwd, so paths
    # built from it are correct no matter where you run it from.
    SCRIPT_DIR = Path(__file__).resolve().parent      # .../analytics/src
    ANALYTICS_DIR = SCRIPT_DIR.parent                  # .../analytics

    DATASET_DIR = (
        ANALYTICS_DIR
        / "dataset/raw/kit-obd2/10.35097-1130/data/dataset/OBD-II-Dataset"
    )

    all_trips = load_all_trips(DATASET_DIR)

    print("Combined shape:", all_trips.shape)
    print("Number of trips:", all_trips["trip_id"].nunique())

    print("\nRows per trip (sanity check vs. original inspection: 6,829-86,654):")
    print(all_trips.groupby("trip_id").size().describe())

    print("\nCondition label counts (sanity check vs. original inspection):")
    print(all_trips.groupby("trip_id")["condition"].first().value_counts())

    print("\nNaN counts across the whole combined set:")
    print(all_trips.isna().sum())

    print("\nNumeric summary (whole combined set):")
    print(all_trips.describe())

    # Save the cleaned, combined dataset so step 2 (feature engineering)
    # starts from this instead of re-running all 81 files through the
    # loader every time.
    out_path = ANALYTICS_DIR / "dataset/processed/kit_combined.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    all_trips.to_parquet(out_path, index=False)
    print(f"\nSaved combined dataset to: {out_path}")