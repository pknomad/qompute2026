from __future__ import annotations

import pytest

from qtrust.analysis import (
    analytic_raw_fidelity,
    bell_fidelity,
    correlation_from_counts,
    parse_counts,
)


def test_raw_count_parsing_and_correlation() -> None:
    data, accepted, rejected = parse_counts({"00": 45, "11": 45, "01": 5, "10": 5}, with_detector=False)
    correlation, standard_error, usable = correlation_from_counts(data)
    assert (accepted, rejected, usable) == (100, 0, 100)
    assert correlation == pytest.approx(0.8)
    assert 0.0 < standard_error < 0.1


def test_detector_count_parsing_uses_s_d1_d0_order() -> None:
    data, accepted, rejected = parse_counts(
        {"000": 30, "011": 20, "101": 7, "110": 3}, with_detector=True
    )
    assert data == {"00": 30, "01": 0, "10": 0, "11": 20}
    assert accepted == 50
    assert rejected == 10


def test_phi_plus_fidelity_from_ideal_correlations() -> None:
    assert bell_fidelity({"X": 1.0, "Y": -1.0, "Z": 1.0}) == pytest.approx(1.0)


@pytest.mark.parametrize("p", [0.0, 0.02, 0.1, 0.2, 0.5])
def test_analytic_fidelity_is_physical(p: float) -> None:
    assert 0.0 <= analytic_raw_fidelity(p) <= 1.0

