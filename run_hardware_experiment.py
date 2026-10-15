"""Run the device-like study and write its results, figure, and metadata."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

import matplotlib
import numpy as np
import pandas as pd
import qiskit
import qiskit_aer
import qiskit_ibm_runtime

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from qtrust.hardware import (  # noqa: E402
    BASE_RATES,
    BASIS_GATES,
    DETECTOR_LAYOUT,
    FAKE_MANILA_LABEL,
    FAKE_MANILA_NO_READOUT_LABEL,
    LINE,
    MITIGATED_UNCERTAINTY,
    RAW_LAYOUT,
    STRATEGIES,
    TRANSPILER_OPTIMIZATION_LEVEL,
    UNMITIGATED_UNCERTAINTY,
    HardwareConfig,
    run_hardware_study,
)

# strategy -> (color, marker/line style, legend label). raw+swap+romit stays in the CSV but off the plot.
STYLE = {
    "raw": ("#da1e28", "o-", "raw"),
    "raw+swap": ("#198038", "D-", "raw + detector's SWAP, no check"),
    "detected": ("#8a3ffc", "s-", "parity detected"),
    "raw+romit": ("#da1e28", "o--", "raw + readout mitigation (no error bars)"),
    "detected+romit": ("#8a3ffc", "s--", "detected + readout mitigation (no error bars)"),
}


def plot(frame, path: Path) -> None:
    synthetic = frame[frame["source"].str.startswith("synthetic")]
    manila = frame[frame["source"] == FAKE_MANILA_LABEL]
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.4))
    ax = axes[0]
    for strategy, (color, fmt, label) in STYLE.items():
        rows = synthetic[synthetic["strategy"] == strategy].sort_values("scale")
        yerr = None if bool(rows["readout_mitigated"].all()) else rows["fidelity_standard_error"]
        ax.errorbar(
            rows["scale"],
            rows["fidelity"],
            yerr=yerr,
            fmt=fmt,
            color=color,
            label=label,
            capsize=3,
        )
    ax.set_xscale("symlog", linthresh=0.25)
    ax.set_xlabel("synthetic scale (1x: p_cx=1%, p_1q=0.05%, p_readout=2%)")
    ax.set_ylabel("Bell fidelity F(Phi+)")
    ax.set_title("Synthetic device-like model")
    ax.axhline(0.5, color="gray", ls=":", lw=1)
    ax.legend(fontsize=7)

    ax = axes[1]
    det = synthetic[synthetic["strategy"] == "detected"].sort_values("scale")
    ax.plot(det["scale"], det["acceptance_rate"], "s-", color="#8a3ffc", label="acceptance rate (detected)")
    ax.set_xscale("symlog", linthresh=0.25)
    ax.set_xlabel("synthetic noise scale")
    ax.set_ylabel("fraction of shots kept")
    ax.set_title("Cost of detection on a 5-qubit line")
    ax.legend(fontsize=8, loc="upper right")
    cx = synthetic.groupby("strategy")["cx_count"].max()
    ax.text(
        0.03, 0.04,
        f"routed CNOTs: raw {int(cx['raw'])}, swap control {int(cx['raw+swap'])}, detected {int(cx['detected'])}",
        transform=ax.transAxes, fontsize=9,
    )

    ax = axes[2]
    if manila.empty:
        ax.axis("off")
        ax.text(0.5, 0.5, "FakeManilaV2 snapshot not run", ha="center", va="center")
    else:
        strategies = ["raw", "raw+swap", "detected"]
        labels = ["raw", "SWAP control", "detected"]
        x = np.arange(len(strategies))
        indexed = manila.set_index("strategy")
        raw_rows = indexed.loc[strategies]
        mitigated_rows = indexed.loc[[f"{name}+romit" for name in strategies]]
        ax.bar(
            x - 0.18,
            raw_rows["fidelity"],
            0.36,
            yerr=raw_rows["fidelity_standard_error"],
            color="#4589ff",
            capsize=3,
            label="unmitigated",
        )
        ax.bar(
            x + 0.18,
            mitigated_rows["fidelity"],
            0.36,
            color="#08bdba",
            hatch="//",
            label="readout mitigated (no error bars)",
        )
        acceptance = float(raw_rows.loc["detected", "acceptance_rate"])
        ax.set_xticks(x, labels)
        ax.set_ylim(0.5, 1.02)
        ax.set_ylabel("Bell fidelity F(Phi+)")
        ax.set_title(
            f"FakeManilaV2 historical snapshot\nDetected acceptance: {acceptance:.1%}"
        )
        ax.axhline(0.5, color="gray", ls=":", lw=1)
        ax.legend(fontsize=7, loc="lower right")

    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def metadata(config: HardwareConfig, runtime_seconds: float) -> dict[str, object]:
    """Return the complete provenance record for the hardware-style study."""

    strategies = [name for name, _, _, _ in STRATEGIES]
    return {
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "shots_per_basis": config.shots,
        "shots_per_readout_calibration_circuit": config.shots,
        "seed_simulator": config.seed_simulator,
        "seed_transpiler": config.seed_transpiler,
        "optimization_level": TRANSPILER_OPTIMIZATION_LEVEL,
        "runtime_seconds": runtime_seconds,
        "software_versions": {
            "python": platform.python_version(),
            "qiskit": qiskit.__version__,
            "qiskit_aer": qiskit_aer.__version__,
            "qiskit_ibm_runtime": qiskit_ibm_runtime.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "basis_gates": BASIS_GATES,
        "coupling_map_edges": [list(edge) for edge in sorted(LINE.get_edges())],
        "initial_layouts": {"raw": RAW_LAYOUT, "raw+swap": DETECTOR_LAYOUT, "detected": DETECTOR_LAYOUT},
        "synthetic_base_rates": BASE_RATES,
        "synthetic_scales": list(config.scales),
        "fake_manila": {
            "included": config.include_fake_manila,
            "identity": "FakeManilaV2 bundled historical calibration snapshot",
            "current_hardware_performance": False,
            "source_labels": [FAKE_MANILA_LABEL, FAKE_MANILA_NO_READOUT_LABEL],
        },
        "strategies": strategies + [f"{name}+romit" for name in strategies],
        "readout_calibration": {
            "method": "two-qubit 4x4 assignment-matrix inversion",
            "prepared_states": ["00", "01", "10", "11"],
            "physical_qubits": "calibrated where each compiled strategy measures its data bits after routing",
            "postprocessing": "solve, clip negative probabilities to zero, and renormalize",
        },
        "uncertainty": {
            "unmitigated": UNMITIGATED_UNCERTAINTY,
            "readout_mitigated": MITIGATED_UNCERTAINTY,
        },
        "outputs": {
            "results": "results/hardware_results.csv",
            "figure": "figures/hardware_noise.png",
            "metadata": "results/hardware_run_metadata.json",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", type=int, default=8192)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--skip-fake-manila", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=ROOT)
    args = parser.parse_args()

    config = HardwareConfig(shots=args.shots, seed_simulator=args.seed, seed_transpiler=args.seed, include_fake_manila=not args.skip_fake_manila)
    start = perf_counter()
    frame = run_hardware_study(config)
    runtime_seconds = perf_counter() - start
    results_dir = args.output_dir / "results"
    figures_dir = args.output_dir / "figures"
    results_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(results_dir / "hardware_results.csv", index=False)
    plot(frame, figures_dir / "hardware_noise.png")
    (results_dir / "hardware_run_metadata.json").write_text(
        json.dumps(metadata(config, runtime_seconds), indent=2) + "\n",
        encoding="utf-8",
    )

    columns = [
        "source", "strategy", "data_qubits", "fidelity", "fidelity_standard_error", "acceptance_rate",
        "cx_count", "circuit_depth", "fidelity_improvement_vs_raw", "fidelity_improvement_vs_swap_control",
    ]
    with np.printoptions(precision=3):
        print(frame[columns].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"Completed hardware-style study in {runtime_seconds:.2f} s")
    print(f"Metadata: {results_dir / 'hardware_run_metadata.json'}")


if __name__ == "__main__":
    main()
