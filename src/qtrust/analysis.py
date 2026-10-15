"""Count parsing, Bell fidelity estimation, and statistical uncertainty."""

from __future__ import annotations

from collections.abc import Mapping
from math import sqrt


def analytic_raw_fidelity(data_noise_p: float) -> float:
    """Return the exact Phi-plus fidelity for independent data-qubit X errors."""

    return (1.0 - data_noise_p) ** 2 + data_noise_p**2


def analytic_acceptance(data_noise_p: float) -> float:
    """Return ideal parity-check acceptance for independent data-qubit X errors."""

    return analytic_raw_fidelity(data_noise_p)


def _clean_key(key: str) -> str:
    cleaned = key.replace(" ", "")
    if not cleaned or any(bit not in "01" for bit in cleaned):
        raise ValueError(f"Unsupported count key {key!r}.")
    return cleaned


def parse_counts(
    counts: Mapping[str, int], *, with_detector: bool
) -> tuple[dict[str, int], int, int]:
    """Return data counts, accepted shots, and rejected shots.

    Detector keys follow Qiskit's displayed order ``s d1 d0``. Syndrome-one
    events are excluded before correlations are calculated.
    """

    data_counts = {"00": 0, "01": 0, "10": 0, "11": 0}
    accepted = 0
    rejected = 0
    expected_width = 3 if with_detector else 2

    for raw_key, value in counts.items():
        key = _clean_key(raw_key)
        if len(key) != expected_width:
            raise ValueError(
                f"Count key {raw_key!r} has width {len(key)}; expected {expected_width}."
            )
        if value < 0:
            raise ValueError("Count values cannot be negative.")
        if with_detector and key[0] == "1":
            rejected += int(value)
            continue
        accepted += int(value)
        data_counts[key[-2:]] += int(value)

    return data_counts, accepted, rejected


def correlation_from_counts(data_counts: Mapping[str, int]) -> tuple[float, float, int]:
    """Estimate a two-qubit Pauli correlation and its standard error."""

    usable_shots = sum(int(data_counts.get(key, 0)) for key in ("00", "01", "10", "11"))
    if usable_shots <= 0:
        raise ValueError("No usable shots remain after postselection.")
    even = int(data_counts.get("00", 0)) + int(data_counts.get("11", 0))
    odd = int(data_counts.get("01", 0)) + int(data_counts.get("10", 0))
    correlation = (even - odd) / usable_shots
    standard_error = sqrt(max(0.0, 1.0 - correlation**2) / usable_shots)
    return correlation, standard_error, usable_shots


def bell_fidelity(correlations: Mapping[str, float]) -> float:
    """Estimate target Phi-plus fidelity from XX, YY, and ZZ correlations."""

    missing = {"X", "Y", "Z"} - set(correlations)
    if missing:
        raise ValueError(f"Missing correlations for bases: {sorted(missing)}")
    fidelity = (
        1.0 + correlations["X"] - correlations["Y"] + correlations["Z"]
    ) / 4.0
    if not -1e-9 <= fidelity <= 1.0 + 1e-9:
        raise ValueError(f"Calculated fidelity {fidelity:.6f} is outside physical bounds.")
    return min(1.0, max(0.0, fidelity))


def fidelity_standard_error(errors: Mapping[str, float]) -> float:
    """Propagate independent correlation errors into Bell fidelity."""

    missing = {"X", "Y", "Z"} - set(errors)
    if missing:
        raise ValueError(f"Missing standard errors for bases: {sorted(missing)}")
    return 0.25 * sqrt(sum(errors[basis] ** 2 for basis in ("X", "Y", "Z")))


def relative_infidelity_reduction(raw_fidelity: float, detected_fidelity: float) -> float | None:
    """Return the fraction of raw infidelity removed by detection."""

    raw_infidelity = 1.0 - raw_fidelity
    if raw_infidelity <= 1e-12:
        return None
    return 1.0 - (1.0 - detected_fidelity) / raw_infidelity

