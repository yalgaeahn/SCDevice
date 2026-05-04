# Simulation Examples

## SCDevice Simulation Workflow Policy

SCDevice simulation code must reuse the KQCircuits simulation workflow directly. SCDevice scripts are only responsible
for geometry construction, sweep case generation, and SCDevice-specific metadata.

Required conventions:

- Use KQCircuits APIs directly: `export_simulation_oas`, `export_ansys`, `export_elmer`, and `PostProcess`.
- Do not create SCDevice-local Ansys batch wrappers or copied helper scripts.
- Do not modify or replace KQCircuits Ansys helper conventions: `create_capacitive_pi_model.py`, `create_reports.py`,
  `export_solution_data.py`, and `produce_cmatrix_table.py`.
- Q3D capacitance matrix output follows KQCircuits PI-model convention. Diagonal terms are shunt/self PI terms and
  off-diagonal terms are positive mutual PI terms.
- SCDevice-specific target analysis, such as `C_sigma` or transmon frequency, must be a secondary report that reads KQ
  standard outputs. It must not replace KQ result files or reinterpret raw matrices with a different convention.

이 문서는 `SCDevice`에서 시뮬레이션 예제를 작게 실행하는 방법을 정리한다. 기본 순서는 smoke check, 작은 1-case export, HFSS batch 실행, 결과 summary다.

큰 sweep은 처음부터 돌리지 않는다. 먼저 1-case export가 제대로 만들어지는지 확인한 뒤 필요한 파라미터만 명시해서 늘린다.

## Common Setup

PowerShell에서 top-level `SCDevice` checkout으로 이동한다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice
```

이 repo의 KQCircuits Python을 직접 사용한다.

```powershell
$py = ".\KQCircuits\.venv\Scripts\python.exe"
```

export temp path는 top-level `SCDevice\tmp`로 둔다. `KQCircuits\tmp` 안으로 export하지 않는다.

```powershell
New-Item -ItemType Directory -Force "C:\Users\user\JSAHN\SCDevice\tmp"
$env:KQC_TMP_PATH = "C:\Users\user\JSAHN\SCDevice\tmp"
```

영구 설정이 필요하면 한 번만 실행하고, 그 다음 VSCode, KLayout, Ansys, terminal을 다시 연다.

```powershell
[Environment]::SetEnvironmentVariable("KQC_TMP_PATH", "C:\Users\user\JSAHN\SCDevice\tmp", "User")
```

## 1. Readout Resonator Smoke Check

가장 작은 확인 명령이다. 기본값은 resonator length `5200 um` 하나만 export한다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_readout_resonator_sweep.py --smoke-check
```

기본 export 위치:

```text
tmp\sqnl_readout_resonator_sweep_hfss
```

성공하면 최소한 아래 파일들이 생긴다.

```text
simulation.oas
simulation.bat
sqnl_ro_len_5200_cpl_400_gap_27.json
scripts\import_and_simulate.py
```

## 2. Readout Resonator 1-Case HFSS Export

pilot 시뮬레이션용 1-case export다. sweep을 키우기 전에 이 명령으로 geometry와 batch 구성을 먼저 확인한다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_readout_resonator_sweep.py
```

명시적인 output folder를 쓰고 싶으면 `--export-dir`를 준다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_readout_resonator_sweep.py `
    --lengths 5200 `
    --coupling-length 400 `
    --gap 27 `
    --export-dir .\tmp\sqnl_readout_pilot
```

HFSS adaptive/sweep 기본값은 다음과 같다.

```text
frequency      = 5.0 GHz
sweep-start    = 4.0 GHz
sweep-end      = 8.0 GHz
sweep-count    = 201
max-delta-s    = 0.001
maximum-passes = 20
```

처음부터 큰 length/coupling/gap sweep을 넣지 않는다. 길이만 작게 확인하려면 예를 들어 아래처럼 3개 정도부터 시작한다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_readout_resonator_sweep.py `
    --lengths 5100,5200,5300 `
    --export-dir .\tmp\sqnl_readout_len3
```

## 3. Run The Generated HFSS Batch

export folder 안의 `simulation.bat`을 실행한다. 이 batch 파일은 KQCircuits `export_ansys`가 생성한 표준 Ansys import/simulate script를 실행한다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice\tmp\sqnl_readout_resonator_sweep_hfss
.\simulation.bat
```

`--export-dir .\tmp\sqnl_readout_pilot`를 썼다면 그 folder에서 실행한다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice\tmp\sqnl_readout_pilot
.\simulation.bat
```

HFSS 실행 후에는 보통 아래 파일들이 추가된다.

```text
*_project.aedt
*_project.aedtresults\
*_SMatrix.s2p
```

## 4. Summarize Readout Results

HFSS가 `_SMatrix.s2p`를 만든 뒤 summary를 생성한다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice
& $py .\scdevice_pcells\simulations\sqnl_readout_resonator_sweep.py `
    --summarize-only `
    --export-dir .\tmp\sqnl_readout_resonator_sweep_hfss
```

출력 파일:

```text
readout_resonator_summary.csv
readout_resonator_summary.json
```

summary에는 `f0_ghz`, `ql`, `qc_estimate`, `qc_in_target`, `notch_depth_db`가 들어간다. 기본 target은 `Qc = 50000-100000`이다.

## 5. Full-Chip Export Smoke Check

readout pilot이 먼저다. full-chip은 선택한 readout geometry를 넣고 마지막 검증 단계에서 확인한다.

launcher 없이 기본 full-chip export를 확인한다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice
& $py .\scdevice_pcells\simulations\sqnl_full_chip_sim.py --smoke-check
```

기본 export 위치:

```text
tmp\sqnl_full_chip_sim_hfss
```

launcher pad까지 포함한 port sizing 검증은 별도로 실행한다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_full_chip_sim.py `
    --smoke-check `
    --launchers `
    --export-dir .\tmp\sqnl_full_chip_with_launchers
```

test resonator feedline variant를 확인할 때만 `--use-test-resonators`를 추가한다.

```powershell
& $py .\scdevice_pcells\simulations\sqnl_full_chip_sim.py `
    --smoke-check `
    --use-test-resonators `
    --export-dir .\tmp\sqnl_full_chip_test_resonators
```

## 6. Legacy `test.py` Example

`scdevice_pcells\simulations\test.py`는 `DoublePads` 기반 legacy 예제다. Q3D와 eigenmode batch를 둘 다 만든다.

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice
& $py .\scdevice_pcells\simulations\test.py
```

기본 output:

```text
tmp\test_output_q3d
tmp\test_output_eigenmode
```

자세한 설명은 [test-py-simulation-example.md](test-py-simulation-example.md)를 참고한다.

## Troubleshooting

`KQCircuits\tmp` 안에 export가 생기면 `KQC_TMP_PATH`가 적용되지 않은 것이다. 현재 terminal에서 `$env:KQC_TMP_PATH`를 확인하고, GUI나 새 terminal은 환경변수 설정 후 다시 시작한다.

`simulation.bat`이 project JSON이나 scripts folder를 못 찾으면 export folder가 아닌 다른 위치에서 실행했을 가능성이 크다. `simulation.bat`은 export folder 안에서 실행한다.

`--summarize-only`에서 `No *_SMatrix.sNp files found`가 나오면 HFSS batch가 아직 `_SMatrix.s2p`를 쓰지 않은 것이다. 먼저 해당 export folder에서 `simulation.bat`을 실행한다.

S22나 S-parameter convergence가 안 좋으면 HFSS에서 mesh/adaptive pass를 먼저 확인한다. 특히 port가 discontinuity에 너무 가깝거나 feedline 양끝 padding이 짧으면 port 주변 field와 resonator coupling field가 섞여서 수렴이 불안정해질 수 있다.
