from __future__ import annotations

import pytest

from qtrust.experiment import ExperimentConfig, run_experiment


@pytest.fixture(scope="module")
def compact_results():
    config = ExperimentConfig(
        shots=4096,
        data_noise_values=(0.0, 0.10),
        detector_noise_values=(0.0,),
        seed_simulator=31415,
        seed_transpiler=31415,
    )
    return run_experiment(config)[:2]


def test_ideal_bell_correlations_and_syndrome(compact_results) -> None:
    basis, summary = compact_results
    ideal_raw = basis[(basis.strategy == "raw") & (basis.data_noise_p == 0.0)].set_index(
        "measurement_basis"
    )
    assert ideal_raw.loc["X", "correlation"] == pytest.approx(1.0)
    assert ideal_raw.loc["Y", "correlation"] == pytest.approx(-1.0)
    assert ideal_raw.loc["Z", "correlation"] == pytest.approx(1.0)
    ideal_detected = basis[(basis.strategy == "detected") & (basis.data_noise_p == 0.0)]
    assert (ideal_detected.shots_rejected == 0).all()
    assert float(
        summary[(summary.strategy == "raw") & (summary.data_noise_p == 0.0)].fidelity.iloc[0]
    ) == pytest.approx(1.0)


def test_detection_improves_moderate_noise_and_preserves_shot_totals(compact_results) -> None:
    basis, summary = compact_results
    assert (
        basis.shots_accepted + basis.shots_rejected == basis.shots_requested
    ).all()
    assert basis.acceptance_rate.between(0.0, 1.0).all()
    raw = float(summary[(summary.strategy == "raw") & (summary.data_noise_p == 0.10)].fidelity.iloc[0])
    detected = float(
        summary[
            (summary.strategy == "detected")
            & (summary.data_noise_p == 0.10)
            & (summary.detector_noise_q == 0.0)
        ].fidelity.iloc[0]
    )
    assert detected > raw
    assert raw == pytest.approx(0.82, abs=0.03)


def test_seed_reproducibility() -> None:
    config = ExperimentConfig(
        shots=512,
        data_noise_values=(0.05,),
        detector_noise_values=(0.0,),
        seed_simulator=99,
        seed_transpiler=99,
    )
    first_basis, first_summary, _ = run_experiment(config)
    second_basis, second_summary, _ = run_experiment(config)
    assert first_basis.equals(second_basis)
    assert first_summary.equals(second_summary)

