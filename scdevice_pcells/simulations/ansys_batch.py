"""Helpers for local Ansys batch exports in the SCDevice tree."""

import json
from pathlib import Path
from shutil import copy2

from kqcircuits.defaults import ANSYS_EXECUTABLE


LOCAL_ANSYS_HELPER_DIR = Path(__file__).with_name("ansys_local")
SIMULATION_BATCH_FILENAME = "simulation_batch.json"
PYEPR_PARAMETER_FILENAME = "run_pyepr_t1_estimate.json"


def get_pyepr_parameters():
    """Return pyEPR post-processing parameters for local eigenmode sweeps."""
    return {
        "substrate_loss_tangent": 5e-7,
        "dielectric_surfaces": {
            "layerMA": {
                "tan_delta_surf": 9.9e-3,
                "th": 4.8e-9,
                "eps_r": 8,
            },
            "layerMS": {
                "tan_delta_surf": 2.6e-3,
                "th": 0.3e-9,
                "eps_r": 11.4,
            },
            "layerSA": {
                "tan_delta_surf": 2.1e-3,
                "th": 2.4e-9,
                "eps_r": 4,
            },
        },
    }


def write_json_file(path: Path, data) -> Path:
    """Write a UTF-8 JSON file."""
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    return path


def write_simulation_batch_manifest(path: Path, simulations) -> Path:
    """Save exported json filenames for a single-session batch import."""
    manifest_path = path / SIMULATION_BATCH_FILENAME
    json_filenames = [f"{simulation.name}.json" for simulation in simulations]
    return write_json_file(manifest_path, {"json_filenames": json_filenames})


def copy_local_ansys_helpers(path: Path):
    """Copy local batch helper scripts into the export scripts folder."""
    scripts_path = path / "scripts"
    scripts_path.mkdir(exist_ok=True)
    for helper_name in ("import_simulation_batch.py", "run_pyepr_t1_estimate_batch.py"):
        copy2(LOCAL_ANSYS_HELPER_DIR / helper_name, scripts_path / helper_name)


def write_simulation_bat(path: Path, sim_tool: str):
    """Rewrite simulation.bat to run the local single-session batch flow."""
    bat_path = path / "simulation.bat"
    ansys_script = str(Path("scripts").joinpath("import_simulation_batch.py"))
    lines = [
        "@echo off",
        "cd /d %~dp0",
        r'powershell -Command "Get-Process | Where-Object {$_.MainWindowTitle -like \"Run Simulations*\"} | Select -ExpandProperty Id | Export-Clixml -path blocking_pids.xml"',
        "title Run Simulations",
        r'powershell -Command "$sim_pids = Import-Clixml -Path blocking_pids.xml; if ($sim_pids) { echo \"Waiting for $sim_pids\"; Wait-Process $sim_pids -ErrorAction SilentlyContinue }; Remove-Item blocking_pids.xml"',
        f"echo Batch import - {sim_tool}",
        f'"{ANSYS_EXECUTABLE}" -scriptargs "{SIMULATION_BATCH_FILENAME}" -RunScriptAndExit "{ansys_script}"',
    ]
    if sim_tool == "eigenmode":
        pyepr_script = str(Path("scripts").joinpath("run_pyepr_t1_estimate_batch.py"))
        lines.extend(
            [
                "echo Post-process",
                f'python "{pyepr_script}" "{SIMULATION_BATCH_FILENAME}" "{PYEPR_PARAMETER_FILENAME}"',
            ]
        )

    with open(bat_path, "w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(lines) + "\n")


def configure_ansys_batch(path: Path, simulations, sim_tool: str):
    """Write local helper files and a custom batch runner for the export folder."""
    write_simulation_batch_manifest(path, simulations)
    if sim_tool == "eigenmode":
        write_json_file(path / PYEPR_PARAMETER_FILENAME, get_pyepr_parameters())
    copy_local_ansys_helpers(path)
    write_simulation_bat(path, sim_tool)
