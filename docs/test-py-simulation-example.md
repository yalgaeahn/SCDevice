# `test.py` Simulation Example

This document explains `scdevice_pcells/simulations/test.py`, which is a runnable example for exporting and running `DoublePads` simulations through KQCircuits and Ansys Electronics Desktop (AEDT).

The script generates two simulation batches:

- `eigenmode`: exports eigenmode projects and a pyEPR post-processing batch.
- `q3d`: exports Q3D capacitance projects and result extraction files.

It is intentionally written as a local workflow example rather than a reusable library API.

## Prerequisites

Use this from the top-level `SCDevice` checkout with the `KQCircuits` Python environment configured. The usual local layout is:

```text
C:\Users\user\JSAHN\SCDevice
|-- KQCircuits\
|-- scdevice_pcells\
|-- tmp\
```

KQCircuits writes generated simulation files under `KQC_TMP_PATH` when that environment variable is set. For this checkout, the recommended value is:

```powershell
$env:KQC_TMP_PATH = "C:\Users\user\JSAHN\SCDevice\tmp"
```

If `KQC_TMP_PATH` is not set, KQCircuits falls back to its default temporary output directory.

## Running The Example

Run the example from the configured KQCircuits/KLayout Python environment:

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice
python .\scdevice_pcells\simulations\test.py
```

Depending on how KQCircuits is configured, this may need to be launched from KLayout or from the same Python environment used by KQCircuits. The script uses `pya`, KQCircuits simulation export helpers, and the configured `ANSYS_EXECUTABLE`.

For each tool, the script creates a generated output directory named from the script stem:

```text
tmp\test_output_eigenmode
tmp\test_output_q3d
```

Each directory contains exported geometry, Ansys JSON input files, a batch manifest, copied helper scripts, and a generated `simulation.bat`.

## Generated Files

The most important generated files are:

- `simulation.oas`: OAS layout export for the generated simulation set.
- `<simulation-name>.gds`: per-case GDS input used by the Ansys export.
- `<simulation-name>.json`: per-case KQCircuits Ansys simulation definition.
- `simulation_batch.json`: manifest listing all per-case JSON files for one AEDT session.
- `scripts\import_simulation_batch.py`: local helper copied into the export directory to import and run every JSON file in one AEDT process.
- `scripts\run_pyepr_t1_estimate_batch.py`: local helper copied for eigenmode pyEPR post-processing.
- `simulation.bat`: Windows batch entrypoint for running the generated batch.

After AEDT runs, typical Q3D output includes:

- `<simulation-name>_project.aedt`: saved AEDT project for the case.
- `<simulation-name>_project.aedtresults\`: AEDT result directory.
- `<simulation-name>_project_CMatrix.txt`: exported capacitance matrix.
- `<simulation-name>_project_results.json`: exported structured result summary.

For eigenmode batches, the generated post-processing step also writes pyEPR artifacts such as `QData_<project>.csv` and saved Hamiltonian files when pyEPR completes successfully.

## What The Script Builds

The example loops over:

```python
sim_tools = ["eigenmode", "q3d"]
```

For each tool, it creates a single-element simulation class for KQCircuits `DoublePads`:

```python
SimClass = get_single_element_sim_class(DoublePads)
```

The common simulation parameters define the simulation box, ports, face stack, and waveguide length. Tool-specific values are then added:

- `eigenmode` enables TLS sheet approximation, sets TLS layer thickness, exports one mode, and adds `simulation_flags: ["pyepr"]`.
- `q3d` disables TLS layer thickness and uses Q3D convergence parameters such as `percent_error`, `maximum_passes`, and `minimum_converged_passes`.

The sweep has two base qubit geometries:

```text
island_island_gap: 70, 150
island_width:      700, 775
```

For each base geometry, it sweeps 51 coupler widths from 20 to 300:

```python
np.linspace(20, 300, 51)
```

That produces 102 simulations per tool. Each simulation name includes the island gap and rounded coupler width, for example:

```text
double_pads_island_dist_70_coupler_width_20
```

## Code Structure

`_get_pyepr_parameters()` returns the dielectric loss and surface participation settings used by the eigenmode pyEPR batch. The data is written to `run_pyepr_t1_estimate.json` only for the eigenmode export.

`_write_json_file()` is a small helper for writing UTF-8 JSON files with indentation.

`_write_simulation_batch_manifest()` writes `simulation_batch.json`. The manifest stores the generated simulation JSON filenames so AEDT can import all cases in one session instead of launching once per case.

`_copy_local_ansys_helpers()` copies local helper scripts from:

```text
scdevice_pcells\simulations\ansys_local
```

into the generated output folder's `scripts\` directory. This makes the exported batch self-contained enough to run from its own output directory.

`_write_simulation_bat()` rewrites the generated `simulation.bat`. The batch file:

- changes to its own directory with `cd /d %~dp0`
- waits for any existing command window titled `Run Simulations`
- runs AEDT with `-scriptargs simulation_batch.json`
- executes `scripts\import_simulation_batch.py` with `-RunScriptAndExit`
- runs pyEPR post-processing after import when the tool is `eigenmode`

`_configure_ansys_batch()` ties those helpers together after KQCircuits exports the simulation files.

The main loop creates the simulation objects, exports `simulation.oas`, exports Ansys input files, and then writes the local batch runner.

## Running The Generated Ansys Batch

After `test.py` exports a batch, run the generated `simulation.bat` from the output directory:

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice\tmp\test_output_q3d
.\simulation.bat
```

The generated batch currently runs AEDT in graphical mode with a command shaped like:

```bat
"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe" -scriptargs "simulation_batch.json" -RunScriptAndExit "scripts\import_simulation_batch.py"
```

To run the same generated batch in non-graphical mode, add `-ng` after `ansysedt.exe`:

```bat
"C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe" -ng -scriptargs "simulation_batch.json" -RunScriptAndExit "scripts\import_simulation_batch.py"
```

For a one-off PowerShell command:

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice\tmp\test_output_q3d
& "C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe" -ng -scriptargs "simulation_batch.json" -RunScriptAndExit "scripts\import_simulation_batch.py"
```

To keep a log while running AEDT:

```powershell
Set-Location C:\Users\user\JSAHN\SCDevice\tmp\test_output_q3d
& "C:\Program Files\AnsysEM\v232\Win64\ansysedt.exe" -ng -scriptargs "simulation_batch.json" -RunScriptAndExit "scripts\import_simulation_batch.py" *> batch.log
```

## Practical Notes

Q3D batches can make AEDT appear as `Not Responding` during `AnalyzeAll()` or project import/export work. That does not always mean the job is stuck. Check whether result files are still being updated in the output directory.

For a quick progress check:

```powershell
Get-ChildItem C:\Users\user\JSAHN\SCDevice\tmp\test_output_q3d -Filter "*_project_results.json" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 10 Name, LastWriteTime
```

Large sweeps should be split into smaller batches when desktop responsiveness or failure recovery matters. For example, the current Q3D sweep has 102 cases, and each case opens, solves, exports, saves, and closes its own AEDT project inside one process.

The copied `import_simulation_batch.py` currently calls `oDesktop.TileWindows(0)`. That is harmless in graphical runs, but it is still a GUI-oriented operation. If non-graphical mode is used heavily and AEDT reports issues around window operations, that call is a good first place to review.

## Troubleshooting

If `simulation.bat` cannot find `simulation_batch.json`, make sure it is being run from the generated output directory or that the `cd /d %~dp0` line is still present.

If AEDT reports that a script cannot be found, check that the generated output directory contains:

```text
scripts\import_simulation_batch.py
scripts\run_pyepr_t1_estimate_batch.py
```

If Q3D appears idle, check file timestamps, the AEDT message window, and the Ansys license client log before terminating the process.

If pyEPR fails after the eigenmode import, inspect the generated AEDT project first. The import step and the pyEPR post-processing step are separate; an eigenmode project can be generated successfully even when pyEPR later fails because of environment, package, or Ansys connection issues.
