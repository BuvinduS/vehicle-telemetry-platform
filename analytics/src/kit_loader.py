"""
kit_loader.py — loads ONE KIT OBD-II trip CSV into a clean DataFrame.

Step 1 of the anomaly-detection pipeline: prove the loader works on a
single file before scaling to all 81.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Maps the KIT dataset's verbose column headers to our own schema's
# naming convention (rpm, coolant_temp_c, etc.) — same style as
# mqtt-topics payload field names, so downstream code reads the
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
# We only need the date out of this for now (condition label parsing
# comes later, once we're working across all 81 files).
FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


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
    return df


if __name__ == "__main__":
    # Point this at wherever you unzipped the dataset.
    DATASET_DIR = Path(
        "~/vehicle-telemetry-platform/analytics/dataset/raw/kit-obd2/"
        "10.35097-1130/data/dataset/OBD-II-Dataset"
    ).expanduser()

    sample_file = sorted(DATASET_DIR.glob("*.csv"))[0]
    print(f"Loading: {sample_file.name}\n")

    df = load_trip(sample_file)

    print("Shape:", df.shape)
    print("\nColumns:", list(df.columns))
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nTimestamp range:", df["timestamp"].min(), "->", df["timestamp"].max())
    print("\nNaN counts:")
    print(df.isna().sum())
    print("\nNumeric summary:")
    print(df.describe())