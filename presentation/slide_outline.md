# Q TRUST Eight Slide Presentation Outline

## Slide 1 The Trust Question

- Track 3 question: when does error detection make a noisy quantum result more credible?
- Target: a Bell state with a known correct answer.
- Main result: at `p=0.10`, fidelity rose from `0.821 +/- 0.003` to `1.000` after ideal parity postselection, while 81.9% of shots survived.
- Visual: `figures/fidelity_vs_noise.png`.

## Slide 2 Bell Fidelity Needs Three Bases

- Target state: `|Phi+> = (|00> + |11>)/sqrt(2)`.
- Z counts alone also fit a classical mixture.
- Measure `XX`, `YY`, and `ZZ`; calculate `F=[1+XX-YY+ZZ]/4`.
- Visual: raw circuit plus the three ideal correlations.

## Slide 3 Controlled Noise and Analytic Check

- Independent X error on each data qubit with probability `p`.
- Exact reference: `F_raw=(1-p)^2+p^2`.
- Seven-point sweep from `p=0` to `0.20`, 8,192 shots per basis.
- Evidence: maximum simulation-versus-theory deviation was 0.0072.

## Slide 4 Parity Error Detector

- One ancilla and two CNOTs measure Z parity.
- Keep `s=0`; reject `s=1`.
- Count convention: `s d1 d0`.
- Visual: `figures/circuit_detector.png`.

## Slide 5 Main Fidelity Result

- At `p=0.05`: raw `0.905 +/- 0.002`, detected `1.000`.
- At `p=0.10`: raw `0.821 +/- 0.003`, detected `1.000`.
- At `p=0.20`: raw `0.687 +/- 0.004`, detected `1.000`.
- State explicitly that these are conditional results under controlled X noise.
- Visual: `figures/fidelity_vs_noise.png`.

## Slide 6 The Price of Detection

- Hardware overhead: +1 qubit, +2 CNOTs, +1 measurement.
- At `p=0.10`, acceptance was 0.819 and the sampling multiplier was 1.22x.
- At `p=0.20`, acceptance was 0.679 and the multiplier was 1.47x.
- Visual: `figures/detection_cost.png`.

## Slide 7 Noisy Detector and Limits

- Sweep detector depolarizing probability through `q=0.02`.
- At `p=0, q=0.02`, detection harmed fidelity by 0.0178.
- At `p=0.10, q=0.02`, it still improved fidelity by 0.1606.
- Limits: X-only data channel, no arbitrary phase detection, simulation only, postselection rather than correction.
- Visual: `figures/detector_usefulness.png`.

## Slide 8 Access and Conclusion

- Trustworthy evidence costs qubits, gates, shots, runtime, and cloud access.
- Publish raw and handled outcomes together with yield, uncertainty, and assumptions.
- Conclusion: use detection when its conditional-fidelity gain exceeds detector error and discarded-shot cost.
- Final screen: repository reproduction command and team/video links.

