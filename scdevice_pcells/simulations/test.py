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

import logging
import sys
from pathlib import Path

import numpy as np

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

from scdevice_pcells.simulations.ansys_batch import configure_ansys_batch


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
    configure_ansys_batch(dir_path, simulations, sim_tool)

logging.info(f"Total simulations: {len(simulations)}")
open_with_klayout_or_default_application(oas)
