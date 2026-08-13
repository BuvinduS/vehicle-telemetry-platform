"""
select_sweep_vehicles.py

Phase 0 (per-vehicle model chat): pick a small, reproducible set of VED
vehicles from each powertrain pool (ICE / HEV) to run the volume-sweep
experiment against ("how much of a vehicle's own history is enough
before a self-trained model is trustworthy?").

Selection criteria (agreed with the person, not picked silently):
  - Only vehicles from the TEST split of the existing VED-ICE / VED-HEV
    manifests (ved_train_val_split.py's output). These vehicles were
    never used to train or validate the sealed cross-vehicle models, so
    reusing them here for a different experiment doesn't leak
    information back into any comparison we might later want to make
    against the original population-model results.
  - Bucketed into row-count terciles (low / medium / high) *within*
    each pool, then one vehicle sampled per tercile per pool, with a
    fixed random seed for reproducibility. This gives spread in "how
    much a vehicle is normally driven" without hand-picking specific
    vehicles by eye.
  - ICE and HEV pools are handled and reported completely separately —
    never pooled together, consistent with how the rest of this
    project's VED work treats the two powertrain types.

ASSUMPTIONS ABOUT INPUT FILES — CHECK THESE BEFORE RUNNING:
This script was written without access to the actual repo/manifest
files (different sandbox from where the VED pipeline actually lives),
so the column names/paths below are best-guesses based on how
`model_details.md` describes the pipeline. Adjust the CONFIG block to
match your actual manifest schema if the column names differ — the
script will fail loudly (not silently) on a missing/misnamed column
via the assertions in `load_manifest()`.

Expected manifest shape (one row per vehicle), per powertrain pool:
    vehicle_id   : unique VED vehicle identifier
    split        : 'train' / 'val' / 'test'
    row_count    : total telemetry rows for that vehicle (used for the
                   row-count-balanced bin-packing split already
                   described in model_details.md §10.1 — if your
                   manifest doesn't carry this column, point
                   ROW_COUNT_SOURCE at the raw VED loader output
                   instead and this script will compute it directly)

If powertrain type (ICE vs HEV) isn't a column in a combined manifest,
this script expects two separate manifest files instead (one per
pool) — see MANIFEST_PATHS below.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------
# CONFIG — adjust to match your actual files before running
# ---------------------------------------------------------------------

# One manifest CSV per powertrain pool, each with at least
# ['vehicle_id', 'split'] columns, and ideally 'row_count' too.
MANIFEST_PATHS = {
    "ICE": "dataset/processed/split/ved_ice_split_manifest.csv",
    "HEV": "dataset/processed/split/ved_hev_split_manifest.csv",
}

# If a manifest doesn't already carry row_count, fall back to computing
# it from the raw per-vehicle VED telemetry files living under this
# directory (one file per vehicle, named `<vehicle_id>.csv` or similar
# — adjust `count_rows_for_vehicle()` below to match actual layout).
RAW_DATA_DIR = "data/ved_raw"

N_TERCILES = 3          # low / medium / high row-count buckets per pool
N_PER_TERCILE = 1        # vehicles sampled per tercile per pool
                          # -> N_TERCILES * N_PER_TERCILE vehicles per pool
RANDOM_SEED = 42          # fixed, per this project's reproducibility convention

OUTPUT_PATH = "dataset/processed/split/sweep_vehicle_selection.csv"

# ---------------------------------------------------------------------


def load_manifest(pool: str, path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"[{pool}] Manifest not found at '{path}'. Update MANIFEST_PATHS "
            f"in the CONFIG block to point at the real ved_train_val_split.py "
            f"output for this pool."
        )
    df = pd.read_csv(p)

    # Normalize known real-world column name variants to this script's
    # internal names. Add more entries here if other manifests differ.
    RENAME_MAP = {
        "VehId": "vehicle_id",
        "n_rows": "row_count",
    }
    df = df.rename(columns={k: v for k, v in RENAME_MAP.items() if k in df.columns})

    required = {"vehicle_id", "split"}
    missing = required - set(df.columns)
    assert not missing, (
        f"[{pool}] Manifest at '{path}' is missing required column(s): "
        f"{missing}. Found columns: {list(df.columns)}. Adjust this "
        f"script's column-name assumptions or fix the manifest."
    )

    df["split"] = df["split"].str.lower().str.strip()
    return df


def ensure_row_counts(pool: str, df: pd.DataFrame) -> pd.DataFrame:
    if "row_count" in df.columns:
        return df

    print(
        f"[{pool}] No 'row_count' column in manifest — computing directly "
        f"from raw data under '{RAW_DATA_DIR}'. This may be slow for large "
        f"files; consider caching row_count back into the manifest once "
        f"correct.",
        file=sys.stderr,
    )
    raw_dir = Path(RAW_DATA_DIR)
    counts = []
    for vid in df["vehicle_id"]:
        counts.append(count_rows_for_vehicle(raw_dir, vid))
    df = df.copy()
    df["row_count"] = counts
    return df


def count_rows_for_vehicle(raw_dir: Path, vehicle_id) -> int:
    """
    Best-guess file layout: one CSV per vehicle named '<vehicle_id>.csv'.
    Adjust the glob pattern here if the real VED raw layout differs
    (e.g. one file per trip, needing a groupby/sum instead of a single
    file's row count).
    """
    candidate = raw_dir / f"{vehicle_id}.csv"
    if not candidate.exists():
        raise FileNotFoundError(
            f"Expected raw data file '{candidate}' not found while computing "
            f"row_count for vehicle '{vehicle_id}'. Fix RAW_DATA_DIR or "
            f"count_rows_for_vehicle() to match the actual VED raw layout, "
            f"or add a 'row_count' column to the manifest directly to skip "
            f"this step entirely."
        )
    # Fast row count without loading full contents into memory.
    with open(candidate, "rb") as f:
        return sum(1 for _ in f) - 1  # minus header


def select_from_pool(pool: str, test_df: pd.DataFrame, rng: np.random.Generator,
                      per_tercile: int) -> pd.DataFrame:
    if len(test_df) < N_TERCILES:
        raise ValueError(
            f"[{pool}] Only {len(test_df)} test-split vehicles available, "
            f"need at least {N_TERCILES} to form terciles. Reduce "
            f"N_TERCILES or check the manifest's split labeling."
        )

    ranked = test_df.sort_values("row_count").reset_index(drop=True)
    tercile_labels = pd.qcut(
        ranked.index, q=N_TERCILES, labels=["low", "medium", "high"][:N_TERCILES]
    )
    ranked = ranked.assign(row_count_tercile=tercile_labels)

    selected_rows = []
    for tercile, group in ranked.groupby("row_count_tercile", observed=True):
        n = min(per_tercile, len(group))
        picked = group.sample(n=n, random_state=rng.integers(0, 2**32 - 1))
        selected_rows.append(picked)

    selected = pd.concat(selected_rows, ignore_index=True)
    selected["powertrain"] = pool
    return selected[["vehicle_id", "powertrain", "row_count", "row_count_tercile"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed", type=int, default=RANDOM_SEED,
        help="Random seed for reproducible sampling (default: %(default)s)",
    )
    parser.add_argument(
        "--per-tercile", type=int, default=N_PER_TERCILE,
        help="Vehicles to sample per row-count tercile per pool (default: %(default)s)",
    )
    parser.add_argument(
        "--output", type=str, default=OUTPUT_PATH,
        help="Where to write the selection CSV (default: %(default)s)",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)

    all_selections = []
    for pool, path in MANIFEST_PATHS.items():
        df = load_manifest(pool, path)
        df = ensure_row_counts(pool, df)

        test_df = df[df["split"] == "test"].copy()
        print(f"[{pool}] {len(test_df)} vehicles in test split, "
              f"row_count range [{test_df['row_count'].min()}, "
              f"{test_df['row_count'].max()}]")

        selected = select_from_pool(pool, test_df, rng, args.per_tercile)
        all_selections.append(selected)

        print(f"[{pool}] Selected {len(selected)} vehicles:")
        print(selected.to_string(index=False))
        print()

    result = pd.concat(all_selections, ignore_index=True)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)
    print(f"Wrote selection ({len(result)} vehicles total: "
          f"{(result['powertrain'] == 'ICE').sum()} ICE / "
          f"{(result['powertrain'] == 'HEV').sum()} HEV) to '{out_path}'")
    print(
        "\nNext step: plug these vehicle_id values into the temporal "
        "split + volume-sweep script (Phase 0/1) — one independent "
        "sweep per vehicle, not pooled."
    )


if __name__ == "__main__":
    main()