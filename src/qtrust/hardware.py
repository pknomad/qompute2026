"""Hardware-like noise study: when does parity detection stop paying for itself?

The main experiment uses a controlled X-error channel that the Z-parity check is
built to catch. This module reruns the same raw-versus-detected comparison under
noise that looks like a real device instead:

* every two-qubit gate is noisy, including the Bell CNOT and the detector CNOTs,
* single-qubit gates are (slightly) noisy,
* readout is noisy, which a parity check cannot see, and
* the circuits are routed on a five-qubit line (the ``FakeManilaV2`` coupling
  map), so the detector pays for a SWAP that the logical circuit hides.

Two noise sources are compared: a synthetic device model whose three error
rates are scaled together by a factor ``scale`` (``scale=1`` is roughly a
2021-class Falcon processor such as ibmq_manila; ``scale~4`` is 2016-class;
``scale~0.4`` matches the two-qubit error of a 2026 Heron), and the calibration
snapshot shipped with ``qiskit_ibm_runtime``'s ``FakeManilaV2``.

Readout-error mitigation (a 4x4 assignment-matrix inversion from four
calibration circuits on the data qubits) is included as the natural comparison:
it targets exactly the error the parity check is blind to.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from qiskit import QuantumCircuit, transpile
from qiskit.transpiler import CouplingMap
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

from .analysis import bell_fidelity, correlation_from_counts, fidelity_standard_error, parse_counts
from .circuits import build_bell_experiment

BASIS_GATES = ["cx", "id", "rz", "sx", "x"]
LINE = CouplingMap.from_line(5)
RAW_LAYOUT = [1, 2]          # data0, data1 on adjacent line qubits
DETECTOR_LAYOUT = [1, 2, 3]  # data0, data1, syndrome: one detector CNOT needs routing

BASE_RATES = {"p_cx": 0.010, "p_1q": 0.0005, "p_ro": 0.020}


@dataclass(frozen=True)
class HardwareConfig:
    shots: int = 8192
    seed_simulator: int = 2026
    seed_transpiler: int = 2026
    scales: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
    include_fake_manila: bool = True


def device_noise_model(p_cx: float, p_1q: float, p_ro: float) -> NoiseModel:
    """Depolarizing gate errors plus symmetric readout error on every qubit."""

    model = NoiseModel(basis_gates=BASIS_GATES)
    if p_1q > 0:
        model.add_all_qubit_quantum_error(depolarizing_error(p_1q, 1), ["sx", "x"])
    if p_cx > 0:
        model.add_all_qubit_quantum_error(depolarizing_error(p_cx, 2), ["cx"])
    if p_ro > 0:
        model.add_all_qubit_readout_error(ReadoutError([[1 - p_ro, p_ro], [p_ro, 1 - p_ro]]))
    return model


def scaled_rates(scale: float) -> dict[str, float]:
    return {key: min(1.0, value * scale) for key, value in BASE_RATES.items()}


def fake_manila_backend() -> tuple[AerSimulator, dict[str, float]]:
    """Aer simulator built from the FakeManilaV2 calibration snapshot, plus its median rates."""

    from qiskit_ibm_runtime.fake_provider import FakeManilaV2

    backend = FakeManilaV2()
    target = backend.target
    cx = np.median([target["cx"][q].error for q in target["cx"] if target["cx"][q] is not None])
    sx = np.median([target["sx"][(q,)].error for q in range(backend.num_qubits)])
    ro = np.median([target["measure"][(q,)].error for q in range(backend.num_qubits)])
    return AerSimulator.from_backend(backend), {"p_cx": float(cx), "p_1q": float(sx), "p_ro": float(ro)}


def _compile(circuit: QuantumCircuit, layout: list[int], seed: int) -> QuantumCircuit:
    return transpile(
        circuit,
        basis_gates=BASIS_GATES,
        coupling_map=LINE,
        initial_layout=layout,
        optimization_level=1,
        seed_transpiler=seed,
    )


def _resources(compiled: QuantumCircuit) -> dict[str, int]:
    ops = compiled.count_ops()
    return {
        "num_qubits": len({q for ins in compiled.data for q in ins.qubits if ins.operation.name != "barrier"}),
        "circuit_depth": int(compiled.depth()),
        "cx_count": int(ops.get("cx", 0)),
        "measurement_count": int(ops.get("measure", 0)),
    }


def readout_assignment_matrix(backend: AerSimulator, shots: int, seed: int) -> np.ndarray:
    """4x4 matrix M[measured, prepared] for the two data qubits at RAW_LAYOUT."""

    matrix = np.zeros((4, 4))
    for column, (bit0, bit1) in enumerate(itertools.product("01", repeat=2)):
        circuit = QuantumCircuit(2, 2)
        if bit0 == "1":
            circuit.x(0)
        if bit1 == "1":
            circuit.x(1)
        circuit.measure([0, 1], [0, 1])
        compiled = _compile(circuit, RAW_LAYOUT, seed)
        counts = backend.run(compiled, shots=shots, seed_simulator=seed).result().get_counts()
        for key, value in counts.items():
            measured = key.replace(" ", "")[::-1]  # d0 d1
            matrix[int(measured, 2), column] += value / shots
    return matrix


def mitigate_counts(data_counts: dict[str, int], matrix: np.ndarray) -> dict[str, float]:
    """Invert the assignment matrix on post-selected data counts (keys ``d1 d0``)."""

    order = ["00", "10", "01", "11"]  # index = int(d0 d1) built from key d1 d0
    vector = np.array([data_counts[key] for key in order], dtype=float)
    total = vector.sum()
    corrected = np.clip(np.linalg.solve(matrix, vector / total), 0.0, None)
    corrected = corrected / corrected.sum() * total
    return {key: float(corrected[index]) for index, key in enumerate(order)}


def run_case(
    backend: AerSimulator,
    *,
    with_detector: bool,
    shots: int,
    seed_simulator: int,
    seed_transpiler: int,
    assignment_matrix: np.ndarray | None = None,
) -> dict[str, Any]:
    correlations: dict[str, float] = {}
    errors: dict[str, float] = {}
    accepted_total = 0
    resources: dict[str, int] = {}
    for basis in ("X", "Y", "Z"):
        logical = build_bell_experiment(basis, with_detector=with_detector, inject_noise=False)
        compiled = _compile(logical, DETECTOR_LAYOUT if with_detector else RAW_LAYOUT, seed_transpiler)
        resources = {key: max(resources.get(key, 0), value) for key, value in _resources(compiled).items()}
        counts = backend.run(compiled, shots=shots, seed_simulator=seed_simulator).result().get_counts()
        data_counts, accepted, _ = parse_counts(counts, with_detector=with_detector)
        if assignment_matrix is not None:
            data_counts = mitigate_counts(data_counts, assignment_matrix)  # type: ignore[assignment]
        correlation, standard_error, _ = correlation_from_counts(
            {key: int(round(value)) for key, value in data_counts.items()}
        )
        correlations[basis] = correlation
        errors[basis] = standard_error
        accepted_total += accepted
    strategy = ("detected" if with_detector else "raw") + ("+romit" if assignment_matrix is not None else "")
    return {
        "strategy": strategy,
        "fidelity": bell_fidelity(correlations),
        "fidelity_standard_error": fidelity_standard_error(errors),
        "correlation_XX": correlations["X"],
        "correlation_YY": correlations["Y"],
        "correlation_ZZ": correlations["Z"],
        "acceptance_rate": accepted_total / (3 * shots),
        **resources,
    }


def run_hardware_study(config: HardwareConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sources: list[tuple[str, float, AerSimulator, dict[str, float]]] = []
    for scale in config.scales:
        rates = scaled_rates(scale)
        sources.append((f"synthetic x{scale:g}", scale, AerSimulator(noise_model=device_noise_model(**rates)), rates))
    if config.include_fake_manila:
        backend, rates = fake_manila_backend()
        sources.append(("FakeManilaV2 snapshot", np.nan, backend, rates))
    for label, scale, backend, rates in sources:
        matrix = readout_assignment_matrix(backend, config.shots, config.seed_simulator)
        for with_detector in (False, True):
            for use_matrix in (False, True):
                result = run_case(
                    backend,
                    with_detector=with_detector,
                    shots=config.shots,
                    seed_simulator=config.seed_simulator,
                    seed_transpiler=config.seed_transpiler,
                    assignment_matrix=matrix if use_matrix else None,
                )
                rows.append({"source": label, "scale": scale, **rates, **result})
    frame = pd.DataFrame(rows)
    raw = frame[frame["strategy"] == "raw"].set_index("source")["fidelity"]
    frame["fidelity_improvement_vs_raw"] = frame["fidelity"] - frame["source"].map(raw)
    return frame
