"""
ved_train_val_split.py — vehicle-level train/val/test split for the
VED-derived ICE/HEV featured datasets (output of ved_feature_engineering.py).

Split at the VEHICLE level, not the trip level, unlike KIT's
train_val_split.py. This matters much more here than it did for KIT:
KIT was a single vehicle, so trip-level was the only split that made any
sense at all (there was no vehicle-level generalization to test). VED has
real multi-vehicle diversity (210 ICE / 89 HEV vehicles), so the entire
point of using it is to test whether the model generalizes to vehicles
it's never seen — a trip-level split would let the same vehicle appear in
both train and val/test, which doesn't test that at all.

Row-count-balanced greedy assignment, not pure random-by-vehicle:
per-vehicle row counts are heavily skewed (confirmed during inspection:
187 to 887,056 rows/vehicle), so a random 70/15/15 split BY VEHICLE COUNT
could easily land far from 70/15/15 BY ROW COUNT purely by chance (e.g.
val randomly drawing several of the largest vehicles). Vehicles are
sorted largest-first and each one is assigned to whichever split is
currently furthest below its row-count target — a standard balanced
bin-packing heuristic. A fixed random seed still shuffles vehicles within
same-size ties, for reproducibility without a fixed processing order
introducing bias.

No target/loss to speak of at this stage — Isolation Forest is
unsupervised (see chat discussion), so there's nothing here analogous to
KIT's stratification-by-label. The only thing being balanced is row
volume, so downstream train/val/test each have a representative sample of
driving conditions rather than, say, val ending up disproportionately
short trips just because small vehicles happened to cluster there.

Writes an explicit VehId -> split manifest CSV for auditability, same
principle as KIT's trip -> split manifest.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

SPLIT_RATIOS = {"train": 0.70, "val": 0.15, "test": 0.15}
RANDOM_SEED = 42


def balanced_vehicle_split(veh_rows: pd.Series, ratios: dict[str, float], seed: int) -> dict[int, str]:
    """Assign each VehId to train/val/test, balancing by total row count.

    Greedy largest-first bin-packing: process vehicles from largest to
    smallest, at each step assigning the current vehicle to whichever
    split is currently furthest below its row-count target (as a
    fraction of that split's target). Ties (equal deficit, or equal row
    count) broken by a seeded shuffle so the result is reproducible but
    not an artifact of VehId ordering.
    """
    total_rows = veh_rows.sum()
    targets = {split: total_rows * frac for split, frac in ratios.items()}
    running = {split: 0 for split in ratios}

    rng = random.Random(seed)
    veh_ids = list(veh_rows.index)
    rng.shuffle(veh_ids)  # break ties among equal-row-count vehicles reproducibly
    veh_ids.sort(key=lambda v: veh_rows[v], reverse=True)  # stable sort keeps shuffle as tiebreak

    assignment: dict[int, str] = {}
    for veh in veh_ids:
        # Deficit = how far below target (as a fraction of target) each split
        # currently is; assign to whichever split has the largest deficit.
        deficits = {
            split: (targets[split] - running[split]) / targets[split]
            for split in ratios
        }
        chosen = max(deficits, key=deficits.get)
        assignment[veh] = chosen
        running[chosen] += veh_rows[veh]

    return assignment


def split_dataset(input_path: Path, output_dir: Path, reuse_manifest: Path | None = None) -> None:
    print(f"Loading {input_path}...", file=sys.stderr)
    df = pd.read_parquet(input_path)
    print(f"  {len(df):,} rows, {df.VehId.nunique()} vehicles", file=sys.stderr)

    veh_rows = df.groupby("VehId").size()

    if reuse_manifest is not None:
        print(f"Reusing existing vehicle assignments from {reuse_manifest} "
              f"(NOT recomputing a fresh split) — for apples-to-apples comparison "
              f"across pipeline variants (e.g. different window lengths) that "
              f"should hold the train/val/test vehicle split constant.", file=sys.stderr)
        prior = pd.read_csv(reuse_manifest)
        assignment = dict(zip(prior["VehId"], prior["split"]))
        missing = set(veh_rows.index) - set(assignment)
        if missing:
            raise ValueError(
                f"{len(missing)} vehicles in {input_path} have no assignment in "
                f"{reuse_manifest} — the two datasets don't share the same vehicle pool "
                f"(e.g. different --window-seconds dropped different short trips down to "
                f"zero rows for a vehicle entirely). Vehicles: {sorted(missing)[:10]}..."
            )
    else:
        assignment = balanced_vehicle_split(veh_rows, SPLIT_RATIOS, RANDOM_SEED)

    df["split"] = df["VehId"].map(assignment)

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = input_path.stem.replace("_featured", "")

    manifest = (
        pd.Series(assignment, name="split")
        .rename_axis("VehId")
        .reset_index()
        .merge(veh_rows.rename("n_rows"), on="VehId")
        .sort_values(["split", "n_rows"], ascending=[True, False])
    )
    manifest_path = output_dir / f"{prefix}_split_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote manifest: {manifest_path}", file=sys.stderr)

    print("\nAchieved split proportions:", file=sys.stderr)
    total_rows = len(df)
    total_vehicles = df.VehId.nunique()
    for split in SPLIT_RATIOS:
        sub = df[df.split == split]
        n_veh = sub.VehId.nunique()
        n_rows = len(sub)
        print(
            f"  {split:5s}: {n_veh:4d} vehicles ({100*n_veh/total_vehicles:5.1f}%)  "
            f"{n_rows:>10,} rows ({100*n_rows/total_rows:5.1f}%)  target {100*SPLIT_RATIOS[split]:.0f}%",
            file=sys.stderr,
        )

    for split in SPLIT_RATIOS:
        out_path = output_dir / f"{prefix}_{split}.parquet"
        df[df.split == split].drop(columns="split").to_parquet(out_path, index=False)
        print(f"Wrote {out_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Path to ved_ice_featured.parquet or ved_hev_featured.parquet")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write train/val/test parquet files + manifest")
    parser.add_argument("--reuse-manifest", type=Path, default=None, help="Optional path to an existing *_split_manifest.csv — reuse its VehId->split assignments instead of computing a fresh balanced split (for comparing pipeline variants on identical vehicle pools)")
    args = parser.parse_args()

    split_dataset(args.input, args.output_dir, reuse_manifest=args.reuse_manifest)


if __name__ == "__main__":
    main()