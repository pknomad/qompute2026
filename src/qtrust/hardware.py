"""Hardware-like noise study: when does parity detection stop paying for itself?

The main experiment uses a controlled X-error channel that the Z-parity check is
built to catch. This module reruns the same raw-versus-detected comparison under
noise that looks like a real device instead:

* every two-qubit gate is noisy, including the Bell CNOT and the detector CNOTs,
* single-qubit gates are (slightly) noisy,
* readout is noisy, which a parity check cannot see, and
* the circuits are routed on a five-qubit line (the ``FakeManilaV2`` coupling
  map), so the detector pays for a SWAP that the logical circuit hides.

Two noise sources are compared: a synthetic device model whose three explicitly
defined error probabilities are scaled together by a factor ``scale``, and the
historical calibration snapshot shipped with ``qiskit_ibm_runtime``'s
``FakeManilaV2``, run once as supplied and once with its readout error removed.
The synthetic scale is not mapped to a hardware generation or calibration
metric.

Three circuits are compared on every source:

* ``raw``: the Bell pair, data qubits on physical ``RAW_LAYOUT``;
* ``raw+swap``: the Bell pair plus the SWAP the router inserts for the detector,
  with NO parity check. The routed detector reads ``data_1`` from a different
  physical qubit than the raw circuit does, and on a device with uneven readout
  error that move alone changes the answer. This control pays the same move, so
  ``detected`` minus ``raw+swap`` isolates what the parity check itself does;
* ``detected``: the parity-checked circuit, syndrome-one shots rejected.

Readout-error mitigation (a 4x4 assignment-matrix inversion from four
calibration circuits) is included as the natural comparison: it targets exactly
the error the parity check is blind to. The matrix is calibrated on the physical
qubits each circuit's data bits are actually read from after routing, not on the
initial layout.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from qiskit import AncillaRegister, ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit.transpiler import CouplingMap
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, ReadoutError, depolarizing_error

from .analysis import bell_fidelity, correlation_from_counts, fidelity_standard_error, parse_counts
from .circuits import Basis, build_bell_experiment

BASIS_GATES = ["cx", "id", "rz", "sx", "x"]
LINE = CouplingMap.from_line(5)
RAW_LAYOUT = [1, 2]          # data0, data1 on adjacent line qubits
DETECTOR_LAYOUT = [1, 2, 3]  # data0, data1, syndrome: one detector CNOT needs routing

BASE_RATES = {"p_cx": 0.010, "p_1q": 0.0005, "p_ro": 0.020}
TRANSPILER_OPTIMIZATION_LEVEL = 1

FAKE_MANILA_LABEL = "FakeManilaV2 snapshot"
FAKE_MANILA_NO_READOUT_LABEL = "FakeManilaV2 snapshot, readout error removed"
UNMITIGATED_UNCERTAINTY = "binomial shot-only plug-in estimate"
MITIGATED_UNCERTAINTY = (
    "omitted: calibration, assignment-matrix inversion, and clipping uncertainty "
    "are not propagated"
)


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


def synthetic_source_label(scale: float) -> str:
    """Return a neutral label tied only to the defined synthetic baseline."""

    return f"synthetic {scale:g}x baseline"


def fake_manila_backend(*, readout_error: bool = True) -> tuple[AerSimulator, dict[str, float]]:
    """Aer simulator built from the FakeManilaV2 calibration snapshot, plus its median rates.

    With ``readout_error=False`` the gate and relaxation noise are kept but the
    per-qubit readout errors are dropped, which isolates what the parity check
    can and cannot see.
    """

    from qiskit_ibm_runtime.fake_provider import FakeManilaV2

    backend = FakeManilaV2()
    target = backend.target
    cx = np.median([target["cx"][q].error for q in target["cx"] if target["cx"][q] is not None])
    sx = np.median([target["sx"][(q,)].error for q in range(backend.num_qubits)])
    ro = np.median([target["measure"][(q,)].error for q in range(backend.num_qubits)])
    rates = {"p_cx": float(cx), "p_1q": float(sx), "p_ro": float(ro) if readout_error else 0.0}
    if readout_error:
        return AerSimulator.from_backend(backend), rates
    return AerSimulator(noise_model=NoiseModel.from_backend(backend, readout_error=False)), rates


def fake_manila_readout_errors() -> dict[int, float]:
    """Per-physical-qubit readout error of the FakeManilaV2 snapshot, for reporting."""

    from qiskit_ibm_runtime.fake_provider import FakeManilaV2

    backend = FakeManilaV2()
    return {q: float(backend.target["measure"][(q,)].error) for q in range(backend.num_qubits)}


def build_raw(basis: Basis) -> QuantumCircuit:
    return build_bell_experiment(basis, with_detector=False, inject_noise=False)


def build_detected(basis: Basis) -> QuantumCircuit:
    return build_bell_experiment(basis, with_detector=True, inject_noise=False)


def build_swap_control(basis: Basis) -> QuantumCircuit:
    """Raw Bell pair that pays the detector's SWAP but runs no parity check.

    On the five-qubit line the detector's second CNOT forces the router to move
    ``data_1`` onto the syndrome's wire, so the detected circuit reads its data
    from different physical qubits than the raw circuit does. This control moves
    ``data_1`` the same way, measures it there, and skips the check, so the
    comparison between it and ``detected`` isolates the parity check itself.
    Count keys are ``d1 d0``, like the raw circuit.
    """

    basis = basis.upper()  # type: ignore[assignment]
    data = QuantumRegister(2, "data")
    spare = AncillaRegister(1, "spare")
    bits = ClassicalRegister(2, "bits")
    circuit = QuantumCircuit(data, spare, bits, name=f"bell_swapctl_{basis}")
    circuit.h(data[0])
    circuit.cx(data[0], data[1])
    circuit.swap(data[1], spare[0])
    measured = [data[0], spare[0]]
    if basis == "X":
        circuit.h(measured)
    elif basis == "Y":
        circuit.sdg(measured)
        circuit.h(measured)
    elif basis != "Z":
        raise ValueError(f"Unsupported basis {basis!r}; expected X, Y, or Z.")
    circuit.measure(data[0], bits[0])
    circuit.measure(spare[0], bits[1])
    return circuit


# (strategy name, circuit builder, initial layout, has a syndrome bit to postselect on)
STRATEGIES: tuple[tuple[str, Callable[[Basis], QuantumCircuit], list[int], bool], ...] = (
    ("raw", build_raw, RAW_LAYOUT, False),
    ("raw+swap", build_swap_control, DETECTOR_LAYOUT, False),
    ("detected", build_detected, DETECTOR_LAYOUT, True),
)
SWAP_CONTROL = "raw+swap"


def _compile(circuit: QuantumCircuit, layout: list[int], seed: int) -> QuantumCircuit:
    return transpile(
        circuit,
        basis_gates=BASIS_GATES,
        coupling_map=LINE,
        initial_layout=layout,
        optimization_level=TRANSPILER_OPTIMIZATION_LEVEL,
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


def measured_physical_qubits(compiled: QuantumCircuit) -> dict[int, int]:
    """Map each classical bit index to the physical qubit the compiled circuit reads it from.

    Routing can move a logical qubit, so the initial layout does not say where a
    data bit is measured. Read it off the final ``measure`` instructions instead.
    """

    mapping: dict[int, int] = {}
    for instruction in compiled.data:
        if instruction.operation.name == "measure":
            qubit = compiled.find_bit(instruction.qubits[0]).index
            clbit = compiled.find_bit(instruction.clbits[0]).index
            mapping[clbit] = qubit
    return mapping


def readout_assignment_matrix(
    backend: AerSimulator,
    shots: int,
    seed: int,
    physical_qubits: tuple[int, int] = (RAW_LAYOUT[0], RAW_LAYOUT[1]),
) -> np.ndarray:
    """4x4 matrix M[measured, prepared] for the two data bits read at ``physical_qubits``.

    ``physical_qubits`` must be where the data bits are actually read in the
    compiled circuit (see ``measured_physical_qubits``), not the initial layout.
    On a device with uneven readout error, a matrix calibrated on the wrong qubit
    over- or under-corrects and can push the estimator past 1.
    """

    matrix = np.zeros((4, 4))
    for column, (bit0, bit1) in enumerate(itertools.product("01", repeat=2)):
        circuit = QuantumCircuit(2, 2)
        if bit0 == "1":
            circuit.x(0)
        if bit1 == "1":
            circuit.x(1)
        circuit.measure([0, 1], [0, 1])
        compiled = _compile(circuit, list(physical_qubits), seed)
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
    strategy: str,
    build: Callable[[Basis], QuantumCircuit],
    layout: list[int],
    with_detector: bool,
    shots: int,
    seed_simulator: int,
    seed_transpiler: int,
    assignment_matrices: dict[tuple[int, int], np.ndarray] | None = None,
) -> dict[str, Any]:
    """Run one strategy in all three bases; mitigate readout if a matrix cache is given.

    ``assignment_matrices`` is filled lazily, one matrix per physical data-qubit
    pair, so every strategy is corrected with a matrix calibrated on the qubits
    it was actually read from.
    """

    correlations: dict[str, float] = {}
    errors: dict[str, float] = {}
    accepted_total = 0
    resources: dict[str, int] = {}
    data_qubits: set[tuple[int, int]] = set()
    for basis in ("X", "Y", "Z"):
        compiled = _compile(build(basis), layout, seed_transpiler)
        resources = {key: max(resources.get(key, 0), value) for key, value in _resources(compiled).items()}
        measured = measured_physical_qubits(compiled)
        pair = (measured[0], measured[1])
        data_qubits.add(pair)
        counts = backend.run(compiled, shots=shots, seed_simulator=seed_simulator).result().get_counts()
        data_counts, accepted, _ = parse_counts(counts, with_detector=with_detector)
        if assignment_matrices is not None:
            if pair not in assignment_matrices:
                assignment_matrices[pair] = readout_assignment_matrix(backend, shots, seed_simulator, pair)
            data_counts = mitigate_counts(data_counts, assignment_matrices[pair])  # type: ignore[assignment]
        correlation, standard_error, _ = correlation_from_counts(
            {key: int(round(value)) for key, value in data_counts.items()}
        )
        correlations[basis] = correlation
        errors[basis] = standard_error
        accepted_total += accepted
    mitigated = assignment_matrices is not None
    return {
        "strategy": strategy + ("+romit" if mitigated else ""),
        "readout_mitigated": mitigated,
        "data_qubits": ";".join(f"q{a},q{b}" for a, b in sorted(data_qubits)),
        "fidelity": bell_fidelity(correlations),
        "fidelity_standard_error": (
            np.nan if mitigated else fidelity_standard_error(errors)
        ),
        "uncertainty_scope": (
            MITIGATED_UNCERTAINTY if mitigated else UNMITIGATED_UNCERTAINTY
        ),
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
        sources.append(
            (
                synthetic_source_label(scale),
                scale,
                AerSimulator(noise_model=device_noise_model(**rates)),
                rates,
            )
        )
    if config.include_fake_manila:
        backend, rates = fake_manila_backend()
        sources.append((FAKE_MANILA_LABEL, np.nan, backend, rates))
        backend, rates = fake_manila_backend(readout_error=False)
        sources.append((FAKE_MANILA_NO_READOUT_LABEL, np.nan, backend, rates))
    for label, scale, backend, rates in sources:
        matrices: dict[tuple[int, int], np.ndarray] = {}
        for strategy, build, layout, with_detector in STRATEGIES:
            for use_matrix in (False, True):
                result = run_case(
                    backend,
                    strategy=strategy,
                    build=build,
                    layout=layout,
                    with_detector=with_detector,
                    shots=config.shots,
                    seed_simulator=config.seed_simulator,
                    seed_transpiler=config.seed_transpiler,
                    assignment_matrices=matrices if use_matrix else None,
                )
                rows.append({"source": label, "scale": scale, **rates, **result})
    frame = pd.DataFrame(rows)
    raw = frame[frame["strategy"] == "raw"].set_index("source")["fidelity"]
    frame["fidelity_improvement_vs_raw"] = frame["fidelity"] - frame["source"].map(raw)
    # Apples to apples: same source, same mitigation, the swap-only control.
    control = (
        frame[frame["strategy"].str.startswith(SWAP_CONTROL)]
        .set_index(["source", "readout_mitigated"])["fidelity"]
        .rename("control_fidelity")
    )
    frame = frame.join(control, on=["source", "readout_mitigated"])
    frame["fidelity_improvement_vs_swap_control"] = frame["fidelity"] - frame.pop("control_fidelity")
    return frame
