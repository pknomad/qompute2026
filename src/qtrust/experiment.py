"""Deterministic Aer experiment orchestration and result aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from .analysis import (
    analytic_acceptance,
    analytic_raw_fidelity,
    bell_fidelity,
    correlation_from_counts,
    fidelity_standard_error,
    parse_counts,
    relative_infidelity_reduction,
)
from .circuits import build_bell_experiment, build_resource_circuit


@dataclass(frozen=True)
class ExperimentConfig:
    """Complete, serializable experiment configuration."""

    shots: int = 8192
    seed_simulator: int = 2026
    seed_transpiler: int = 2026
    data_noise_values: tuple[float, ...] = (0.0, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20)
    detector_noise_values: tuple[float, ...] = (0.0, 0.005, 0.010, 0.020)
    optimization_level: int = 0

    def validate(self) -> None:
        if self.shots <= 0:
            raise ValueError("shots must be positive.")
        for name, values in (
            ("data_noise_values", self.data_noise_values),
            ("detector_noise_values", self.detector_noise_values),
        ):
            if not values:
                raise ValueError(f"{name} cannot be empty.")
            if any(not 0.0 <= value <= 1.0 for value in values):
                raise ValueError(f"{name} must contain probabilities in [0, 1].")


def _resource_metrics(circuit: QuantumCircuit) -> dict[str, int]:
    operations = circuit.count_ops()
    ignored = {"measure", "barrier", "quantum_channel"}
    gate_count = sum(int(count) for name, count in operations.items() if name not in ignored)
    return {
        "num_qubits": circuit.num_qubits,
        "circuit_depth": int(circuit.depth()),
        "total_gate_count": gate_count,
        "cx_count": int(operations.get("cx", 0)),
        "measurement_count": int(operations.get("measure", 0)),
    }


def _make_circuits(config: ExperimentConfig) -> list[QuantumCircuit]:
    circuits: list[QuantumCircuit] = []
    for data_noise_p in config.data_noise_values:
        for basis in ("X", "Y", "Z"):
            circuits.append(
                build_bell_experiment(basis, data_noise_p, with_detector=False)
            )
        for detector_noise_q in config.detector_noise_values:
            for basis in ("X", "Y", "Z"):
                circuits.append(
                    build_bell_experiment(
                        basis,
                        data_noise_p,
                        with_detector=True,
                        detector_noise_q=detector_noise_q,
                    )
                )
    return circuits


def _resource_lookup(config: ExperimentConfig, backend: AerSimulator) -> dict[tuple[str, bool], dict[str, int]]:
    lookup: dict[tuple[str, bool], dict[str, int]] = {}
    for basis in ("X", "Y", "Z"):
        for with_detector in (False, True):
            logical = build_resource_circuit(basis, with_detector=with_detector)
            compiled = transpile(
                logical,
                backend,
                optimization_level=config.optimization_level,
                seed_transpiler=config.seed_transpiler,
            )
            lookup[(basis, with_detector)] = _resource_metrics(compiled)
    return lookup


def _aggregate_summary(basis_results: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    group_columns = ["strategy", "data_noise_p", "detector_noise_q"]
    for (strategy, data_noise_p, detector_noise_q), group in basis_results.groupby(
        group_columns, sort=True
    ):
        by_basis = group.set_index("measurement_basis")
        correlations = {basis: float(by_basis.loc[basis, "correlation"]) for basis in "XYZ"}
        errors = {
            basis: float(by_basis.loc[basis, "correlation_standard_error"])
            for basis in "XYZ"
        }
        fidelity = bell_fidelity(correlations)
        total_requested = int(group["shots_requested"].sum())
        total_accepted = int(group["shots_accepted"].sum())
        acceptance_rate = total_accepted / total_requested
        rows.append(
            {
                "strategy": strategy,
                "data_noise_p": float(data_noise_p),
                "detector_noise_q": float(detector_noise_q),
                "fidelity": fidelity,
                "fidelity_standard_error": fidelity_standard_error(errors),
                "analytic_raw_fidelity": analytic_raw_fidelity(float(data_noise_p)),
                "analytic_ideal_acceptance": analytic_acceptance(float(data_noise_p)),
                "raw_theory_absolute_error": (
                    abs(fidelity - analytic_raw_fidelity(float(data_noise_p)))
                    if strategy == "raw"
                    else np.nan
                ),
                "shots_requested_total": total_requested,
                "shots_accepted_total": total_accepted,
                "acceptance_rate": acceptance_rate,
                "acceptance_spread": float(group["acceptance_rate"].max() - group["acceptance_rate"].min()),
                "shot_cost_multiplier": 1.0 / acceptance_rate,
                "num_qubits": int(group["num_qubits"].max()),
                "max_circuit_depth": int(group["circuit_depth"].max()),
                "max_total_gate_count": int(group["total_gate_count"].max()),
                "max_cx_count": int(group["cx_count"].max()),
                "measurement_count": int(group["measurement_count"].max()),
                "seed_simulator": int(group["seed_simulator"].iloc[0]),
                "seed_transpiler": int(group["seed_transpiler"].iloc[0]),
            }
        )

    summary = pd.DataFrame(rows).sort_values(group_columns).reset_index(drop=True)
    raw_by_p = summary[summary["strategy"] == "raw"].set_index("data_noise_p")["fidelity"]
    improvements: list[float] = []
    reductions: list[float | None] = []
    helped: list[bool] = []
    for row in summary.itertuples():
        if row.strategy == "raw":
            improvements.append(0.0)
            reductions.append(None)
            helped.append(False)
            continue
        raw_fidelity = float(raw_by_p.loc[row.data_noise_p])
        improvement = float(row.fidelity - raw_fidelity)
        improvements.append(improvement)
        reductions.append(relative_infidelity_reduction(raw_fidelity, float(row.fidelity)))
        helped.append(improvement > 0.0)
    summary["fidelity_improvement"] = improvements
    summary["relative_infidelity_reduction"] = reductions
    summary["detection_helped"] = helped
    return summary


def validate_results(basis_results: pd.DataFrame, summary_results: pd.DataFrame, config: ExperimentConfig) -> None:
    """Fail loudly when a scientific or bookkeeping invariant is violated."""

    if basis_results["experiment_id"].duplicated().any():
        raise RuntimeError("Duplicate experiment identifiers were generated.")
    if basis_results.isna().any().any():
        raise RuntimeError("Basis-level results contain missing values.")
    if not (
        basis_results["shots_accepted"] + basis_results["shots_rejected"]
        == basis_results["shots_requested"]
    ).all():
        raise RuntimeError("Accepted and rejected shots do not sum to requested shots.")
    if not basis_results["acceptance_rate"].between(0.0, 1.0).all():
        raise RuntimeError("Acceptance rate left the physical interval [0, 1].")
    if not summary_results["fidelity"].between(-1e-9, 1.0 + 1e-9).all():
        raise RuntimeError("Fidelity left the physical interval [0, 1].")
    raw = summary_results[summary_results["strategy"] == "raw"]
    tolerance = 6.0 * raw["fidelity_standard_error"] + 0.01
    if not (raw["raw_theory_absolute_error"] <= tolerance).all():
        raise RuntimeError("Raw simulation does not follow the analytic bit-flip curve.")
    if 0.10 in config.data_noise_values and 0.0 in config.detector_noise_values:
        raw_fidelity = float(raw.loc[raw["data_noise_p"] == 0.10, "fidelity"].iloc[0])
        detected = summary_results[
            (summary_results["strategy"] == "detected")
            & (summary_results["data_noise_p"] == 0.10)
            & (summary_results["detector_noise_q"] == 0.0)
        ]
        if detected.empty or float(detected["fidelity"].iloc[0]) <= raw_fidelity:
            raise RuntimeError("Ideal detection failed to improve fidelity at p=0.10.")


def run_experiment(config: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Run the full batched simulator study and return basis and summary data."""

    config.validate()
    backend = AerSimulator(method="density_matrix")
    circuits = _make_circuits(config)
    compiled = transpile(
        circuits,
        backend,
        optimization_level=config.optimization_level,
        seed_transpiler=config.seed_transpiler,
    )
    resources = _resource_lookup(config, backend)

    start = perf_counter()
    result = backend.run(
        compiled,
        shots=config.shots,
        seed_simulator=config.seed_simulator,
    ).result()
    runtime_seconds = perf_counter() - start

    rows: list[dict[str, Any]] = []
    for index, circuit in enumerate(compiled):
        metadata = circuit.metadata or {}
        basis = str(metadata["basis"])
        with_detector = bool(metadata["with_detector"])
        data_noise_p = float(metadata["data_noise_p"])
        detector_noise_q = float(metadata["detector_noise_q"])
        counts = result.get_counts(index)
        data_counts, accepted, rejected = parse_counts(counts, with_detector=with_detector)
        correlation, standard_error, usable = correlation_from_counts(data_counts)
        if usable != accepted:
            raise RuntimeError("Parsed data count total disagrees with accepted-shot count.")
        strategy = "detected" if with_detector else "raw"
        experiment_id = f"{strategy}_p{data_noise_p:.3f}_q{detector_noise_q:.3f}_{basis}"
        rows.append(
            {
                "experiment_id": experiment_id,
                "strategy": strategy,
                "measurement_basis": basis,
                "data_noise_p": data_noise_p,
                "detector_noise_q": detector_noise_q,
                "shots_requested": config.shots,
                "shots_accepted": accepted,
                "shots_rejected": rejected,
                "acceptance_rate": accepted / config.shots,
                "correlation": correlation,
                "correlation_standard_error": standard_error,
                **resources[(basis, with_detector)],
                "seed_simulator": config.seed_simulator,
                "seed_transpiler": config.seed_transpiler,
                "optimization_level": config.optimization_level,
            }
        )

    basis_results = pd.DataFrame(rows).sort_values("experiment_id").reset_index(drop=True)
    summary_results = _aggregate_summary(basis_results)
    validate_results(basis_results, summary_results, config)
    return basis_results, summary_results, runtime_seconds


def save_results(
    basis_results: pd.DataFrame,
    summary_results: pd.DataFrame,
    output_directory: str | Path,
) -> None:
    """Write deterministic CSV outputs."""

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    basis_results.to_csv(output_path / "basis_results.csv", index=False)
    summary_results.to_csv(output_path / "summary_results.csv", index=False)

