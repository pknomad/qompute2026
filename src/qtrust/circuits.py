"""Qiskit circuits for Bell-state preparation, noise, and parity detection."""

from __future__ import annotations

from typing import Literal

from qiskit import AncillaRegister, ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit_aer.noise import depolarizing_error, pauli_error

Basis = Literal["X", "Y", "Z"]


def _validate_probability(value: float, name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, received {value}.")


def _apply_measurement_basis(circuit: QuantumCircuit, data: QuantumRegister, basis: Basis) -> None:
    if basis == "X":
        circuit.h(data)
    elif basis == "Y":
        circuit.sdg(data)
        circuit.h(data)
    elif basis != "Z":
        raise ValueError(f"Unsupported basis {basis!r}; expected X, Y, or Z.")


def build_bell_experiment(
    basis: Basis,
    data_noise_p: float = 0.0,
    *,
    with_detector: bool = False,
    detector_noise_q: float = 0.0,
    inject_noise: bool = True,
) -> QuantumCircuit:
    """Build one Bell-state correlation circuit.

    The single classical register makes Qiskit count keys unambiguous. Raw keys
    are ``d1 d0``. Detector keys are ``s d1 d0``, where ``s=0`` is accepted.
    """

    _validate_probability(data_noise_p, "data_noise_p")
    _validate_probability(detector_noise_q, "detector_noise_q")
    basis = basis.upper()  # type: ignore[assignment]

    data = QuantumRegister(2, "data")
    bits = ClassicalRegister(3 if with_detector else 2, "bits")
    if with_detector:
        syndrome = AncillaRegister(1, "syndrome")
        circuit = QuantumCircuit(data, syndrome, bits, name=f"bell_detect_{basis}")
    else:
        syndrome = None
        circuit = QuantumCircuit(data, bits, name=f"bell_raw_{basis}")

    circuit.h(data[0])
    circuit.cx(data[0], data[1])

    if inject_noise and data_noise_p > 0:
        bit_flip = pauli_error([("X", data_noise_p), ("I", 1.0 - data_noise_p)])
        circuit.append(bit_flip.to_instruction(), [data[0]])
        circuit.append(bit_flip.to_instruction(), [data[1]])

    if with_detector:
        assert syndrome is not None
        detector_error = None
        if inject_noise and detector_noise_q > 0:
            detector_error = depolarizing_error(detector_noise_q, 2).to_instruction()
        for qubit in data:
            circuit.cx(qubit, syndrome[0])
            if detector_error is not None:
                circuit.append(detector_error, [qubit, syndrome[0]])

    _apply_measurement_basis(circuit, data, basis)
    circuit.measure(data[0], bits[0])
    circuit.measure(data[1], bits[1])
    if with_detector:
        assert syndrome is not None
        circuit.measure(syndrome[0], bits[2])

    circuit.metadata = {
        "basis": basis,
        "data_noise_p": float(data_noise_p),
        "detector_noise_q": float(detector_noise_q),
        "with_detector": with_detector,
    }
    return circuit


def build_resource_circuit(basis: Basis, *, with_detector: bool) -> QuantumCircuit:
    """Build the noiseless circuit scaffold used for transparent resource counts."""

    return build_bell_experiment(
        basis,
        with_detector=with_detector,
        data_noise_p=0.0,
        detector_noise_q=0.0,
        inject_noise=False,
    )

