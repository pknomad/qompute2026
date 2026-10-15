# Q TRUST Video Script

## 0:00 to 0:35 The Question

[Show the main fidelity figure.]

Quantum computers return answers even when noise has damaged the calculation. Our Track 3 project asks a narrow, testable question: when does error detection make a Bell-pair result more trustworthy, and when does the detector cost more than it helps?

We built Q TRUST, a reproducible Qiskit benchmark that reports conditional fidelity together with the shots, qubits, gates, and uncertainty required to obtain it.

## 0:35 to 1:25 The Trust Metric

[Show the raw Bell circuit.]

Our known answer is the Bell state Phi-plus. It should produce correlations XX equals one, YY equals minus one, and ZZ equals one.

Checking only the Z basis would be weak evidence because a classical fifty-fifty mixture of 00 and 11 produces the same Z counts. We therefore measure in X, Y, and Z and combine those correlations into target-state fidelity: one plus XX, minus YY, plus ZZ, divided by four.

Each setting uses 8,192 shots per basis. We propagate the finite-shot correlation errors into a fidelity error bar.

## 1:25 to 2:15 Noise and Baseline

[Trace the black analytic curve and blue raw points.]

After Bell preparation, we apply an explicit independent X-error channel to each data qubit. The probability p runs from zero to twenty percent.

This model has a useful exact answer. Zero flips and two flips return the target Bell state, so raw fidelity is the quantity one minus p, squared, plus p squared.

The simulation followed that curve with a maximum absolute deviation of 0.0072. At p equals 0.10, raw fidelity was 0.821 plus or minus 0.003. This agreement is our check that the circuit, bit order, and estimator are working.

## 2:15 to 3:10 The Parity Detector

[Switch to the detector circuit.]

The detector adds one ancilla. Two CNOTs write the data qubits' Z parity onto it. Qiskit displays each count as syndrome, data one, data zero. We keep syndrome zero and reject syndrome one before calculating every correlation.

Under independent X noise, exactly one flip changes even parity to odd parity, so the detector rejects the events that move Phi-plus into the orthogonal Bell state. It cannot catch arbitrary phase errors, and it is postselected error detection rather than error correction.

## 3:10 to 4:25 Main Results

[Return to the fidelity plot, then show the selected-results table.]

The ideal detector retained only target-state outcomes in this controlled model. At p equals 0.05, raw fidelity was 0.905 plus or minus 0.002, while detected fidelity was 1.000. At p equals 0.10, raw fidelity was 0.821 and detected fidelity was 1.000. At p equals 0.20, raw fidelity fell to 0.687 plus or minus 0.004, while the retained sample stayed at 1.000.

That perfect conditional number needs context. It is a result of the deliberately narrow X-error channel and an ideal detector. It does not mean the full device is perfect, and the plug-in error formula returning zero does not prove the true failure probability is zero.

## 4:25 to 5:20 Resource and Sampling Cost

[Show the two-panel cost figure.]

The circuit cost is one additional qubit, two additional CNOTs, and one additional measurement. Maximum transpiled depth rises from five to seven in our documented Aer configuration.

The sampling cost grows with p because more odd-error shots are discarded. At p equals 0.10, 81.9 percent of shots survived, which means about 1.22 raw shots per retained shot. At p equals 0.20, 67.9 percent survived and the multiplier rose to 1.47.

Conditional fidelity and acceptance must be read together. A method that publishes only the improved fidelity hides the price paid for that result.

## 5:20 to 6:15 Detector Noise and Limits

[Show the usefulness heatmap.]

We then added a two-qubit depolarizing channel after each detector CNOT. This reveals the operating region where detection helps.

With perfect data and detector noise q equals 0.02, adding the detector reduced fidelity by 0.0178. There was no data error to remove. At p equals 0.10 with the same detector noise, detected fidelity was 0.981 and the gain over raw was 0.1606.

Our main limitations are deliberate: independent X noise is not a complete IBM hardware model, the check misses arbitrary phase errors, and simulator results do not establish real-device performance. Real routing, readout error, calibration drift, and queue cost can change the boundary.

## 6:15 to 7:05 Device-Like Noise

[Show the device-like noise figure.]

So we tested that. We repeated the comparison with depolarizing error on every CNOT, readout error, and routing on the five-qubit Manila line, where the detector needs a SWAP. That SWAP moves a data qubit, so we added a control: the same Bell pair and SWAP with no parity check.

Under synthetic device noise, detected fidelity was below raw at every scale, and the check itself was worth at most 0.018 over the control. On the FakeManilaV2 snapshot, detection looked like a gain of 0.08. The control explains it: the SWAP moves data one from qubit two, with 9.6 percent readout error, to qubit three, with 1.4 percent. The swap alone reached 0.904 keeping every shot; detection reached 0.897 keeping 88 percent. The real lever was readout mitigation, which recovered 0.16 on that snapshot without discarding a shot.

## 7:05 to 7:30 Conclusion

[Show the final slide with the reproduction command.]

Q TRUST's conclusion is conditional: error detection is worth using when the errors it removes exceed the errors and discarded-shot cost it introduces.

That cost also affects access. Better-funded groups can buy more repetitions and discard more data. Quantum claims should publish raw and handled results, acceptance, resources, noise assumptions, and uncertainty together. The full experiment, tests, CSV evidence, executed notebook, and figures reproduce with one command in the repository.

