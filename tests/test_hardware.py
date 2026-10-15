import numpy as np
import pytest

from qtrust.hardware import HardwareConfig, mitigate_counts, run_hardware_study


def test_identity_mitigation_leaves_counts_unchanged():
    counts = {"00": 400, "01": 50, "10": 30, "11": 520}
    corrected = mitigate_counts(counts, np.eye(4))
    assert corrected == pytest.approx(counts)


def test_noiseless_device_gives_unit_fidelity_for_raw_and_detected():
    frame = run_hardware_study(HardwareConfig(shots=1024, scales=(0.0,), include_fake_manila=False))
    assert set(frame["strategy"]) == {"raw", "detected", "raw+romit", "detected+romit"}
    assert (frame["fidelity"] > 0.99).all()
    assert (frame.loc[frame["strategy"] == "detected", "acceptance_rate"] > 0.99).all()
    assert frame.loc[frame["strategy"] == "detected", "cx_count"].max() > frame.loc[frame["strategy"] == "raw", "cx_count"].max()
