"""Run the hardware-like noise study and write results/hardware_results.csv + figures/hardware_noise.png."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from qtrust.hardware import FAKE_MANILA_LABEL, HardwareConfig, run_hardware_study  # noqa: E402

# strategy -> (color, marker/line style, legend label). raw+swap+romit stays in the CSV but off the plot.
STYLE = {
    "raw": ("#da1e28", "o-", "raw"),
    "raw+swap": ("#198038", "D-", "raw + detector's SWAP, no check"),
    "detected": ("#8a3ffc", "s-", "parity detected"),
    "raw+romit": ("#da1e28", "o--", "raw + readout mitigation"),
    "detected+romit": ("#8a3ffc", "s--", "detected + readout mitigation"),
}


def plot(frame, path: Path) -> None:
    synthetic = frame[frame["source"].str.startswith("synthetic")]
    manila = frame[frame["source"] == FAKE_MANILA_LABEL]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    ax = axes[0]
    for strategy, (color, fmt, label) in STYLE.items():
        rows = synthetic[synthetic["strategy"] == strategy].sort_values("scale")
        ax.errorbar(rows["scale"], rows["fidelity"], yerr=rows["fidelity_standard_error"], fmt=fmt, color=color, label=label, capsize=3)
        if not manila.empty:
            row = manila[manila["strategy"] == strategy].iloc[0]
            ax.scatter([row["p_cx"] / 0.010], [row["fidelity"]], marker="*", s=160, color=color, zorder=5)
    ax.set_xscale("symlog", linthresh=0.25)
    ax.set_xlabel("device noise scale (1 = p_cx 1 %, p_1q 0.05 %, p_readout 2 %)")
    ax.set_ylabel("Bell fidelity F(Phi+)")
    ax.set_title("Device-like noise (stars = FakeManilaV2 snapshot)")
    ax.axhline(0.5, color="gray", ls=":", lw=1)
    ax.legend(fontsize=8)
    ax = axes[1]
    det = synthetic[synthetic["strategy"] == "detected"].sort_values("scale")
    ax.plot(det["scale"], det["acceptance_rate"], "s-", color="#8a3ffc", label="acceptance rate (detected)")
    ax.set_xscale("symlog", linthresh=0.25)
    ax.set_xlabel("device noise scale")
    ax.set_ylabel("fraction of shots kept")
    ax.set_title("Cost of detection on a 5-qubit line")
    ax.legend(fontsize=8, loc="upper right")
    cx = synthetic.groupby("strategy")["cx_count"].max()
    ax.text(
        0.03, 0.04,
        f"routed CNOTs: raw {int(cx['raw'])}, swap control {int(cx['raw+swap'])}, detected {int(cx['detected'])}",
        transform=ax.transAxes, fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--skip-fake-manila", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()

    config = HardwareConfig(shots=args.shots, seed_simulator=args.seed, seed_transpiler=args.seed, include_fake_manila=not args.skip_fake_manila)
    frame = run_hardware_study(config)
    results_dir = args.output_dir / "results"
    figures_dir = args.output_dir / "figures"
    results_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(results_dir / "hardware_results.csv", index=False)
    plot(frame, figures_dir / "hardware_noise.png")

    columns = [
        "source", "strategy", "data_qubits", "fidelity", "fidelity_standard_error", "acceptance_rate",
        "cx_count", "circuit_depth", "fidelity_improvement_vs_raw", "fidelity_improvement_vs_swap_control",
    ]
    with np.printoptions(precision=3):
        print(frame[columns].to_string(index=False, float_format=lambda v: f"{v:.3f}"))


if __name__ == "__main__":
    main()
