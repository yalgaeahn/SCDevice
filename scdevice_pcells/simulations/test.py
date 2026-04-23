# This code is part of KQCircuits
# Copyright (C) 2022 IQM Finland Oy
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see
# https://www.gnu.org/licenses/gpl-3.0.html.
#
# The software distribution should follow IQM trademark policy for open-source software
# (meetiqm.com/iqm-open-source-trademark-policy). IQM welcomes contributions to the code.
# Please see our contribution agreements for individuals (meetiqm.com/iqm-individual-contributor-license-agreement)
# and organizations (meetiqm.com/iqm-organization-contributor-license-agreement).

import json
import logging
import sys
from pathlib import Path
from shutil import copy2

import numpy as np

from kqcircuits.defaults import ANSYS_EXECUTABLE
from kqcircuits.pya_resolver import pya
from kqcircuits.qubits.double_pads import DoublePads
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.single_element_simulation import get_single_element_sim_class
from kqcircuits.util.export_helper import (
    create_or_empty_tmp_directory,
    get_active_or_new_layout,
    open_with_klayout_or_default_application,
)


LOCAL_ANSYS_HELPER_DIR = Path(__file__).with_name("ansys_local")
SIMULATION_BATCH_FILENAME = "simulation_batch.json"
PYEPR_PARAMETER_FILENAME = "run_pyepr_t1_estimate.json"


def _get_pyepr_parameters():
    """Return pyEPR post-processing parameters for the eigenmode sweep."""
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


def _write_json_file(path: Path, data) -> Path:
    """Write a UTF-8 JSON file."""
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)
    return path


def _write_simulation_batch_manifest(path: Path, simulations) -> Path:
    """Save exported json filenames for a single-session batch import."""
    manifest_path = path / SIMULATION_BATCH_FILENAME
    json_filenames = [f"{simulation.name}.json" for simulation in simulations]
    return _write_json_file(manifest_path, {"json_filenames": json_filenames})


def _copy_local_ansys_helpers(path: Path):
    """Copy local batch helper scripts into the export scripts folder."""
    scripts_path = path / "scripts"
    scripts_path.mkdir(exist_ok=True)
    for helper_name in ("import_simulation_batch.py", "run_pyepr_t1_estimate_batch.py"):
        copy2(LOCAL_ANSYS_HELPER_DIR / helper_name, scripts_path / helper_name)


def _write_simulation_bat(path: Path, sim_tool: str):
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


def _configure_ansys_batch(path: Path, simulations, sim_tool: str):
    """Write local helper files and a custom batch runner for the export folder."""
    _write_simulation_batch_manifest(path, simulations)
    if sim_tool == "eigenmode":
        _write_json_file(path / PYEPR_PARAMETER_FILENAME, _get_pyepr_parameters())
    _copy_local_ansys_helpers(path)
    _write_simulation_bat(path, sim_tool)


sim_tools = ["eigenmode", "q3d"]

for sim_tool in sim_tools:
    SimClass = get_single_element_sim_class(DoublePads)
    sim_parameters = {
        "name": "double_pads",
        "use_internal_ports": True,
        "use_ports": True,
        "face_stack": ["1t1"],
        "box": pya.DBox(pya.DPoint(0, 0), pya.DPoint(2000, 2000)),
        "tls_layer_thickness": 5e-3 if sim_tool == "eigenmode" else 0.0,
        "tls_sheet_approximation": sim_tool == "eigenmode",
        "waveguide_length": 200,
    }

    dir_path = create_or_empty_tmp_directory(Path(__file__).stem + f"_output_{sim_tool}")

    export_parameters_ansys = (
        {
            "percent_error": 0.2,
            "maximum_passes": 18,
            "minimum_passes": 2,
            "minimum_converged_passes": 2,
        }
        if sim_tool == "q3d"
        else {
            "max_delta_f": 0.008,
            "mesh_size": {"1t1_gap": 25},
            "maximum_passes": 17,
            "minimum_passes": 1,
            "minimum_converged_passes": 2,
            "n_modes": 1,
            "min_frequency": 0.5,
            "simulation_flags": ["pyepr"],
        }
    )

    export_parameters_ansys = {
        "ansys_tool": sim_tool,
        "path": dir_path,
        "exit_after_run": True,
        **export_parameters_ansys,
    }

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    layout = get_active_or_new_layout()

    simulations = []
    for island_island_gap, island_width, island1_taper_width, island2_taper_width in zip(
        [70, 150], [700, 775], [16.17, 37.6], [39.17, 61.3]
    ):
        name = f"{sim_parameters['name']}_island_dist_{int(island_island_gap)}"
        simulations += [
            SimClass(
                layout,
                **{
                    **sim_parameters,
                    "ground_gap": [900, 900],
                    "a": 5,
                    "b": 20,
                    "coupler_a": 5,
                    "coupler_extent": [round(coupler_width), 20],
                    "island1_extent": [round(island_width), 200],
                    "island2_extent": [round(island_width), 200],
                    "island_island_gap": island_island_gap,
                    "island1_taper_width": island1_taper_width,
                    "island2_taper_width": island2_taper_width,
                    "coupler_offset": 100,
                    "junction_type": "Manhattan",
                    "island2_taper_junction_width": 31.7,
                    "junction_total_length": 39.5,
                    "name": f"{name}_coupler_width_{round(coupler_width)}",
                },
            )
            for coupler_width in np.linspace(20, 300, 51)
        ]

    oas = export_simulation_oas(simulations, dir_path)
    export_ansys(simulations, **export_parameters_ansys)
    _configure_ansys_batch(dir_path, simulations, sim_tool)

logging.info(f"Total simulations: {len(simulations)}")
open_with_klayout_or_default_application(oas)
