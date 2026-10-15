"""Command-line entry point for the complete Q TRUST workflow."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from qtrust.experiment import ExperimentConfig, run_experiment, save_results
from qtrust.plotting import create_all_figures

import matplotlib
import numpy
import pandas
import qiskit
import qiskit_aer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", type=int, default=8192, help="Shots per measurement basis.")
    parser.add_argument("--seed", type=int, default=2026, help="Simulator and transpiler seed.")
    parser.add_argument(
        "--skip-detector-grid",
        action="store_true",
        help="Run only the ideal parity detector (q=0).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT,
        help="Repository-style output root containing results/ and figures/.",
    )
    return parser


def _selected_results_markdown(summary):
    selected_p = [0.02, 0.05, 0.10, 0.20]
    raw = summary[summary["strategy"] == "raw"].set_index("data_noise_p")
    detected = summary[
        (summary["strategy"] == "detected") & (summary["detector_noise_q"] == 0.0)
    ].set_index("data_noise_p")
    lines = [
        "| p | Raw fidelity | Detected fidelity | Acceptance | Shot multiplier | Helped? |",
        "|---:|---:|---:|---:|---:|:---:|",
    ]
    for p in selected_p:
        raw_row = raw.loc[p]
        detected_row = detected.loc[p]
        lines.append(
            f"| {p:.2f} | {raw_row.fidelity:.3f} +/- {raw_row.fidelity_standard_error:.3f} "
            f"| {detected_row.fidelity:.3f} +/- {detected_row.fidelity_standard_error:.3f} "
            f"| {detected_row.acceptance_rate:.3f} | {detected_row.shot_cost_multiplier:.2f}x "
            f"| {'Yes' if detected_row.fidelity_improvement > 0 else 'No'} |"
        )
    return "\n".join(lines) + "\n"


def _update_readme_table(readme_path: Path, table: str) -> None:
    if not readme_path.exists():
        return
    start_marker = "<!-- RESULTS_TABLE_START -->"
    end_marker = "<!-- RESULTS_TABLE_END -->"
    content = readme_path.read_text(encoding="utf-8")
    if start_marker not in content or end_marker not in content:
        return
    before, remainder = content.split(start_marker, maxsplit=1)
    _, after = remainder.split(end_marker, maxsplit=1)
    readme_path.write_text(
        f"{before}{start_marker}\n{table}{end_marker}{after}", encoding="utf-8"
    )


def main() -> int:
    args = _parser().parse_args()
    detector_noise_values = (0.0,) if args.skip_detector_grid else (0.0, 0.005, 0.010, 0.020)
    config = ExperimentConfig(
        shots=args.shots,
        seed_simulator=args.seed,
        seed_transpiler=args.seed,
        detector_noise_values=detector_noise_values,
    )
    basis_results, summary_results, runtime_seconds = run_experiment(config)
    results_dir = args.output_dir / "results"
    figures_dir = args.output_dir / "figures"
    save_results(basis_results, summary_results, results_dir)
    create_all_figures(summary_results, figures_dir)
    selected_table = _selected_results_markdown(summary_results)
    (results_dir / "selected_results.md").write_text(selected_table, encoding="utf-8")
    _update_readme_table(args.output_dir / "README.md", selected_table)
    metadata = {
        "shots_per_basis": config.shots,
        "seed_simulator": config.seed_simulator,
        "seed_transpiler": config.seed_transpiler,
        "optimization_level": config.optimization_level,
        "data_noise_values": list(config.data_noise_values),
        "detector_noise_values": list(config.detector_noise_values),
        "runtime_seconds": runtime_seconds,
        "python": platform.python_version(),
        "qiskit": qiskit.__version__,
        "qiskit_aer": qiskit_aer.__version__,
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "matplotlib": matplotlib.__version__,
    }
    (results_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    raw_error = summary_results.loc[
        summary_results["strategy"] == "raw", "raw_theory_absolute_error"
    ].max()
    print(f"Completed {len(basis_results)} circuits in {runtime_seconds:.2f} s")
    print(f"Maximum raw-vs-analytic fidelity deviation: {raw_error:.5f}")
    print(f"Results: {results_dir}")
    print(f"Figures: {figures_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

