"""
analyze_volume_sweep.py — Phase 2: read ved_per_vehicle_volume_sweep.py's
output and actually answer "how much of a vehicle's own history is enough."

Produces two things per fault type:

1. A plot: detection rate vs. accumulated training-volume (calendar days),
   one line per vehicle, at a fixed fault magnitude (--std-multiple,
   default 3.0 — chosen because earlier KIT/VED work found this was
   roughly where detection fully saturated, not a sweep-magnitude
   decision made fresh here). ICE and HEV vehicles are drawn in
   different colors/styles so the two pools are visually distinguishable
   on one plot without pooling their numbers together.

2. A saturation-point summary table: for each (vehicle, fault_type), the
   smallest actual_train_span_days at which detection first reached 95%
   of that SAME vehicle's own maximum observed detection rate (its
   ceiling, not a fixed absolute target — a vehicle whose detection
   never gets very good at all shouldn't be reported as "saturating
   early" just because it flatlined low). This is the actual candidate
   answer to "how much is enough," per vehicle — meant to be read
   alongside the plot, not instead of it, since a numeric summary can
   hide a curve that's noisy rather than genuinely flat.

Note on duplicate/flat steps: some day_cutoffs in the source data can
share an identical actual_train_span_days (e.g. if no new trip occurred
between two calendar cutoffs — confirmed to happen in the real run's
log). This script deduplicates on (vehicle_id, fault_type, std_multiple,
actual_train_span_days) before plotting/analysis, keeping the last
occurrence, so a flat stretch of trip inactivity doesn't draw as several
overlapping points at the same x-value.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


FPR_TARGETS = [2, 5, 10]  # matches ved_synthetic_fault_injection.py's REFERENCE_FPR_TARGETS


def load_results(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {
        "vehicle_id", "powertrain", "fault_type", "std_multiple",
        "actual_train_span_days", "day_cutoff",
    }
    missing = required - set(df.columns)
    assert not missing, f"Results CSV missing columns: {missing} (found: {list(df.columns)})"
    return df


def dedupe_flat_steps(df: pd.DataFrame) -> pd.DataFrame:
    """Some day_cutoffs can land on an identical actual_train_span_days
    (no new trip occurred between two calendar cutoffs). Keep the last
    occurrence (the widest day_cutoff label for that span) so plots don't
    draw overlapping points."""
    sort_cols = ["vehicle_id", "fault_type", "std_multiple", "actual_train_span_days"]
    return (
        df.sort_values(sort_cols + ["day_cutoff"])
        .drop_duplicates(subset=sort_cols, keep="last")
        .reset_index(drop=True)
    )


def plot_curves(df: pd.DataFrame, fpr: int, std_multiple: float, output_dir: Path) -> None:
    rate_col = f"detect_rate_at_{fpr}pct_fpr"
    if rate_col not in df.columns:
        raise ValueError(
            f"'{rate_col}' not in results — available fpr targets are {FPR_TARGETS}, "
            f"pass --fpr matching one of those."
        )

    subset = df[df["std_multiple"] == std_multiple]
    if subset.empty:
        available = sorted(df["std_multiple"].unique())
        raise ValueError(
            f"No rows at std_multiple={std_multiple}. Available values: {available}"
        )

    fault_types = sorted(subset["fault_type"].unique())
    fig, axes = plt.subplots(1, len(fault_types), figsize=(7 * len(fault_types), 5), squeeze=False)
    axes = axes[0]

    pool_style = {"ICE": {"linestyle": "-", "marker": "o"}, "HEV": {"linestyle": "--", "marker": "s"}}

    for ax, ft in zip(axes, fault_types):
        ft_df = subset[subset["fault_type"] == ft].sort_values("actual_train_span_days")
        for (pool, veh), grp in ft_df.groupby(["powertrain", "vehicle_id"]):
            grp = grp.sort_values("actual_train_span_days")
            style = pool_style.get(pool, {})
            ax.plot(
                grp["actual_train_span_days"], grp[rate_col],
                label=f"{pool} {veh}", alpha=0.85, **style,
            )
        ax.set_title(f"fault_type = {ft}")
        ax.set_xlabel("Accumulated training data (calendar days)")
        ax.set_ylabel(f"Detection rate @ {fpr}% reference FPR")
        ax.set_ylim(-0.05, 1.05)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

    fig.suptitle(f"Detection rate vs. training volume (fault magnitude = {std_multiple}x std)")
    fig.tight_layout()

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"volume_sweep_curves_fpr{fpr}_mult{std_multiple}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Wrote plot: {out_path}", file=sys.stderr)


def saturation_summary(df: pd.DataFrame, fpr: int, std_multiple: float, threshold_frac: float) -> pd.DataFrame:
    """For each (vehicle, fault_type): the smallest actual_train_span_days
    at which detection first reached threshold_frac (default 0.95) of that
    vehicle's OWN max observed detection rate at this magnitude/fpr —
    relative to its own ceiling, not a fixed absolute target.

    CAVEAT, discovered after the second real run: this metric assumes the
    curve rises and plateaus. In practice several vehicles instead show an
    early SPIKE (typically at the very first, single-trip training step —
    plausibly an under-fit model with an artificially narrow "normal"
    reference, making a std-relative fault trivially separable) followed by
    a PERMANENT drop to a lower, stable plateau. For those vehicles this
    metric misleadingly reports "day 0" as the saturation point, when day 0
    is actually the least trustworthy point on the curve, not the most
    mature one. Kept for diagnostic visibility (own_max is still useful to
    see whether a spike occurred at all) — but see stabilization_summary()
    below for the metric that's actually meant to answer "how much history
    is enough."
    """
    rate_col = f"detect_rate_at_{fpr}pct_fpr"
    subset = df[df["std_multiple"] == std_multiple].copy()

    rows = []
    for (pool, veh, ft), grp in subset.groupby(["powertrain", "vehicle_id", "fault_type"]):
        grp = grp.sort_values("actual_train_span_days")
        own_max = grp[rate_col].max()
        target = own_max * threshold_frac

        reached = grp[grp[rate_col] >= target]
        saturation_days = reached["actual_train_span_days"].min() if not reached.empty else None

        rows.append({
            "powertrain": pool,
            "vehicle_id": veh,
            "fault_type": ft,
            "own_max_detect_rate": round(own_max, 3),
            f"saturation_days_at_{int(threshold_frac*100)}pct_of_own_max": (
                round(saturation_days, 1) if saturation_days is not None else None
            ),
        })

    return pd.DataFrame(rows).sort_values(["fault_type", "powertrain", "vehicle_id"])


def stabilization_summary(df: pd.DataFrame, fpr: int, std_multiple: float, tolerance: float) -> pd.DataFrame:
    """For each (vehicle, fault_type): the smallest actual_train_span_days
    beyond which EVERY subsequent step stays within `tolerance` (absolute
    detection-rate difference, default 0.10) of the FINAL (most-data,
    "all") step's value.

    This is the metric that actually answers "how much history is enough,"
    because it's anchored to the curve's long-run/mature behavior rather
    than its historical maximum — an early one-off spike (see
    saturation_summary's caveat above) will NOT count as "stable" unless
    everything after it also stays close to the eventual value; the scan
    runs backward from the final point specifically so a transient spike
    that later drops away gets excluded rather than rewarded.

    Also reports final_detect_rate alongside own_max_detect_rate so a big
    gap between the two is visible at a glance — that gap IS the spike,
    and is itself diagnostic (see chat discussion: it's evidence the
    single-trip model is under-fit, not evidence the vehicle is "easy").
    """
    rate_col = f"detect_rate_at_{fpr}pct_fpr"
    subset = df[df["std_multiple"] == std_multiple].copy()

    rows = []
    for (pool, veh, ft), grp in subset.groupby(["powertrain", "vehicle_id", "fault_type"]):
        grp = grp.sort_values("actual_train_span_days").reset_index(drop=True)
        final_value = grp[rate_col].iloc[-1]
        own_max = grp[rate_col].max()

        stab_day = grp["actual_train_span_days"].iloc[-1]
        for i in range(len(grp) - 2, -1, -1):
            val = grp[rate_col].iloc[i]
            if abs(val - final_value) <= tolerance:
                stab_day = grp["actual_train_span_days"].iloc[i]
            else:
                break

        rows.append({
            "powertrain": pool,
            "vehicle_id": veh,
            "fault_type": ft,
            "final_detect_rate": round(final_value, 3),
            "own_max_detect_rate": round(own_max, 3),
            "max_minus_final_gap": round(own_max - final_value, 3),
            f"stabilizes_from_days_within_{tolerance}": round(stab_day, 1),
        })

    return pd.DataFrame(rows).sort_values(["fault_type", "powertrain", "vehicle_id"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-csv", type=Path, required=True,
                         help="Output of ved_per_vehicle_volume_sweep.py")
    parser.add_argument("--fpr", type=int, default=2, choices=FPR_TARGETS,
                         help="Which reference FPR column to analyze (default: 2)")
    parser.add_argument("--std-multiple", type=float, default=3.0,
                         help="Fault magnitude (as multiple of feature std) to plot/summarize (default: 3.0)")
    parser.add_argument("--saturation-threshold", type=float, default=0.95,
                         help="Fraction of each vehicle's own max detection rate counted as 'saturated' (default: 0.95)")
    parser.add_argument("--stabilization-tolerance", type=float, default=0.10,
                         help="Absolute detect-rate tolerance for the stabilization metric (default: 0.10)")
    parser.add_argument("--output-dir", type=Path, default=Path("dataset/processed/split/volume_sweep_analysis"))
    args = parser.parse_args()

    df = load_results(args.results_csv)
    print(f"Loaded {len(df)} rows, {df['vehicle_id'].nunique()} vehicles", file=sys.stderr)

    df = dedupe_flat_steps(df)
    print(f"{len(df)} rows after deduping flat (identical-span) steps", file=sys.stderr)

    plot_curves(df, args.fpr, args.std_multiple, args.output_dir)

    saturation = saturation_summary(df, args.fpr, args.std_multiple, args.saturation_threshold)
    saturation_path = args.output_dir / "saturation_summary.csv"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    saturation.to_csv(saturation_path, index=False)

    print(f"\n[Diagnostic only — see caveat in saturation_summary()'s docstring] "
          f"Saturation summary (fpr={args.fpr}%, std_multiple={args.std_multiple}, "
          f"threshold={args.saturation_threshold}):", file=sys.stderr)
    print(saturation.to_string(index=False), file=sys.stderr)
    print(f"Wrote {saturation_path}", file=sys.stderr)

    stabilization = stabilization_summary(df, args.fpr, args.std_multiple, args.stabilization_tolerance)
    stabilization_path = args.output_dir / "stabilization_summary.csv"
    stabilization.to_csv(stabilization_path, index=False)

    print(f"\n[This is the one that actually answers 'how much history is enough'] "
          f"Stabilization summary (fpr={args.fpr}%, std_multiple={args.std_multiple}, "
          f"tolerance=±{args.stabilization_tolerance}):", file=sys.stderr)
    print(stabilization.to_string(index=False), file=sys.stderr)
    print(f"Wrote {stabilization_path}", file=sys.stderr)

    print(
        "\nCompare the two tables above: a large max_minus_final_gap flags a "
        "vehicle/fault_type where the very first (single-trip) training step "
        "produced an inflated, likely under-fit reading — the "
        "stabilizes_from_days column is the trustworthy answer for that "
        "case, not the saturation_summary's day. Then check whether "
        "stabilization days (or ceiling levels) cluster by powertrain type "
        "or vary vehicle-by-vehicle regardless of ICE/HEV — that's the real "
        "question this experiment exists to answer.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()