"""Publication-ready figures generated from Q TRUST CSV results."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

from .circuits import build_resource_circuit

RAW_COLOR = "#255F85"
DETECTED_COLOR = "#D1495B"
NOISY_COLOR = "#2A9D8F"
GRID_COLOR = "#D8DEE5"


def _style_axis(axis: plt.Axes) -> None:
    axis.grid(True, color=GRID_COLOR, linewidth=0.8, alpha=0.75)
    axis.spines[["top", "right"]].set_visible(False)


def save_circuit_figures(output_directory: str | Path) -> None:
    """Render raw and parity-detection circuits using Qiskit's drawer."""

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    for filename, detected in (("circuit_raw.png", False), ("circuit_detector.png", True)):
        circuit = build_resource_circuit("Z", with_detector=detected)
        figure = circuit.draw(output="mpl", fold=-1, idle_wires=False, style="iqp")
        figure.savefig(output_path / filename, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(figure)


def plot_fidelity(summary: pd.DataFrame, output_directory: str | Path) -> None:
    """Plot simulated fidelity, theory, uncertainty, and one noisy detector."""

    output_path = Path(output_directory)
    raw = summary[summary["strategy"] == "raw"].sort_values("data_noise_p")
    ideal = summary[
        (summary["strategy"] == "detected") & (summary["detector_noise_q"] == 0.0)
    ].sort_values("data_noise_p")
    available_q = sorted(
        q for q in summary.loc[summary["strategy"] == "detected", "detector_noise_q"].unique() if q > 0
    )

    figure, axis = plt.subplots(figsize=(9.2, 5.6))
    axis.plot(
        raw["data_noise_p"],
        raw["analytic_raw_fidelity"],
        color="#1B1B1B",
        linewidth=2.0,
        label="Raw analytic reference",
    )
    axis.errorbar(
        raw["data_noise_p"],
        raw["fidelity"],
        yerr=raw["fidelity_standard_error"],
        marker="o",
        capsize=3,
        color=RAW_COLOR,
        label="Raw simulation",
    )
    axis.errorbar(
        ideal["data_noise_p"],
        ideal["fidelity"],
        yerr=ideal["fidelity_standard_error"],
        marker="s",
        capsize=3,
        color=DETECTED_COLOR,
        label="Ideal parity detection",
    )
    if available_q:
        representative_q = available_q[min(1, len(available_q) - 1)]
        noisy = summary[
            (summary["strategy"] == "detected")
            & np.isclose(summary["detector_noise_q"], representative_q)
        ].sort_values("data_noise_p")
        axis.errorbar(
            noisy["data_noise_p"],
            noisy["fidelity"],
            yerr=noisy["fidelity_standard_error"],
            marker="^",
            capsize=3,
            color=NOISY_COLOR,
            label=f"Noisy detector (q={representative_q:.3f})",
        )
    axis.axhline(0.5, color="#7A7A7A", linestyle="--", linewidth=1.4, label="Target-state witness threshold")
    axis.set(
        xlabel="Independent data-qubit bit-flip probability p",
        ylabel="Bell-state fidelity",
        title="Parity detection preserves conditional Bell fidelity under bit-flip noise",
        ylim=(0.45, 1.025),
    )
    axis.legend(frameon=False, ncol=2)
    _style_axis(axis)
    figure.tight_layout()
    figure.savefig(output_path / "fidelity_vs_noise.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_detection_cost(summary: pd.DataFrame, output_directory: str | Path) -> None:
    """Plot the accepted fraction and sampling cost of ideal detection."""

    output_path = Path(output_directory)
    ideal = summary[
        (summary["strategy"] == "detected") & (summary["detector_noise_q"] == 0.0)
    ].sort_values("data_noise_p")
    figure, axes = plt.subplots(2, 1, figsize=(8.8, 7.3), sharex=True)
    axes[0].plot(
        ideal["data_noise_p"], ideal["acceptance_rate"], marker="o", color=DETECTED_COLOR
    )
    axes[0].plot(
        ideal["data_noise_p"],
        ideal["analytic_ideal_acceptance"],
        color="#1B1B1B",
        linestyle="--",
        label="Analytic acceptance",
    )
    axes[0].set(ylabel="Accepted shot fraction", title="Detection trades data volume for conditional fidelity")
    axes[0].legend(frameon=False)
    axes[1].plot(
        ideal["data_noise_p"],
        ideal["shot_cost_multiplier"],
        marker="o",
        color=RAW_COLOR,
    )
    axes[1].set(
        xlabel="Independent data-qubit bit-flip probability p",
        ylabel="Raw shots per retained shot",
    )
    for axis in axes:
        _style_axis(axis)
    figure.tight_layout()
    figure.savefig(output_path / "detection_cost.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot_usefulness_map(summary: pd.DataFrame, output_directory: str | Path) -> None:
    """Plot where noisy parity detection improves or harms fidelity."""

    output_path = Path(output_directory)
    detected = summary[summary["strategy"] == "detected"]
    pivot = detected.pivot(
        index="detector_noise_q", columns="data_noise_p", values="fidelity_improvement"
    ).sort_index().sort_index(axis=1)
    values = pivot.to_numpy(dtype=float)
    bound = max(abs(float(np.nanmin(values))), abs(float(np.nanmax(values))), 1e-3)

    x_min, x_max = float(pivot.columns.min()), float(pivot.columns.max())
    y_min, y_max = float(pivot.index.min()), float(pivot.index.max())
    if np.isclose(x_min, x_max):
        x_min, x_max = x_min - 0.005, x_max + 0.005
    if np.isclose(y_min, y_max):
        y_min, y_max = y_min - 0.001, y_max + 0.001

    figure, axis = plt.subplots(figsize=(9.0, 4.9))
    image = axis.imshow(
        values,
        origin="lower",
        aspect="auto",
        cmap="RdBu_r",
        norm=TwoSlopeNorm(vmin=-bound, vcenter=0.0, vmax=bound),
        extent=[x_min, x_max, y_min, y_max],
    )
    x_values = pivot.columns.to_numpy(dtype=float)
    y_values = pivot.index.to_numpy(dtype=float)
    if np.nanmin(values) < 0 < np.nanmax(values):
        axis.contour(x_values, y_values, values, levels=[0.0], colors="black", linewidths=1.3)
    colorbar = figure.colorbar(image, ax=axis, pad=0.02)
    colorbar.set_label("Detected fidelity minus raw fidelity")
    axis.set(
        xlabel="Data bit-flip probability p",
        ylabel="Detector depolarizing probability q",
        title="Operating region where parity detection helps or hurts",
    )
    figure.tight_layout()
    figure.savefig(output_path / "detector_usefulness.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


def create_all_figures(summary: pd.DataFrame, output_directory: str | Path) -> None:
    """Generate all circuit and quantitative figures."""

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    save_circuit_figures(output_path)
    plot_fidelity(summary, output_path)
    plot_detection_cost(summary, output_path)
    plot_usefulness_map(summary, output_path)

