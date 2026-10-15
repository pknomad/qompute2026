import numpy as np
import pytest
from qiskit_aer import AerSimulator

from qtrust.circuits import build_bell_experiment
from qtrust.hardware import (
    DETECTOR_LAYOUT,
    RAW_LAYOUT,
    HardwareConfig,
    _compile,
    build_swap_control,
    measured_physical_qubits,
    mitigate_counts,
    readout_assignment_matrix,
    run_hardware_study,
)


def test_identity_mitigation_leaves_counts_unchanged():
    counts = {"00": 400, "01": 50, "10": 30, "11": 520}
    corrected = mitigate_counts(counts, np.eye(4))
    assert corrected == pytest.approx(counts)


def test_noiseless_device_gives_unit_fidelity_for_every_strategy():
    frame = run_hardware_study(HardwareConfig(shots=1024, scales=(0.0,), include_fake_manila=False))
    assert set(frame["strategy"]) == {
        "raw", "raw+romit", "raw+swap", "raw+swap+romit", "detected", "detected+romit",
    }
    assert (frame["fidelity"] > 0.99).all()
    assert (frame.loc[frame["strategy"] == "detected", "acceptance_rate"] > 0.99).all()
    cx = frame.groupby("strategy")["cx_count"].max()
    assert cx["raw"] < cx["raw+swap"] < cx["detected"]
    # the control is the reference for itself, so its improvement column is exactly zero
    assert (frame.loc[frame["strategy"].str.startswith("raw+swap"), "fidelity_improvement_vs_swap_control"] == 0).all()


def test_swap_control_reads_data_from_the_same_physical_qubits_as_the_detector():
    detected = _compile(build_bell_experiment("Z", with_detector=True, inject_noise=False), DETECTOR_LAYOUT, 2026)
    control = _compile(build_swap_control("Z"), DETECTOR_LAYOUT, 2026)
    det_bits = measured_physical_qubits(detected)
    ctl_bits = measured_physical_qubits(control)
    assert (det_bits[0], det_bits[1]) == (ctl_bits[0], ctl_bits[1])
    # routing moved a data qubit off the raw layout, which is the whole reason the control exists
    assert (det_bits[0], det_bits[1]) != tuple(RAW_LAYOUT)


def test_readout_matrix_is_identity_on_a_noiseless_backend_for_any_qubit_pair():
    matrix = readout_assignment_matrix(AerSimulator(), shots=256, seed=7, physical_qubits=(1, 3))
    assert matrix == pytest.approx(np.eye(4))
