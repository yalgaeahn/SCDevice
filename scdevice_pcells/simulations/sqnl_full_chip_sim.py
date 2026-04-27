# This code is part of KQCircuits
# Copyright (C) 2026 IQM Finland Oy
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not, see
# https://www.gnu.org/licenses/gpl-3.0.html.
#
# The software distribution should follow IQM trademark policy for open-source software
# (meetiqm.com/iqm-open-source-trademark-policy). IQM welcomes contributions to the code.
# Please see our contribution agreements for individuals (meetiqm.com/iqm-individual-contributor-license-agreement)
# and organizations (meetiqm.com/iqm-organization-contributor-license-agreement).

import argparse
import logging
import sys
from pathlib import Path

from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.empty_simulation import EmptySimulation
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.port import EdgePort, InternalPort
from kqcircuits.elements.element import get_refpoints
from kqcircuits.util.export_helper import create_or_empty_tmp_directory, open_with_klayout_or_default_application

from scdevice_pcells.chips.sqnl_chip import SqnlSingle
from scdevice_pcells.simulations.ansys_batch import SIMULATION_BATCH_FILENAME, configure_ansys_batch


LAUNCHER_NAMES = ["NW", "WN", "WS", "SW", "SE", "ES", "EN", "NE"]


def build_sqnl_cell(layout, use_test_resonators=False):
    """Create the SQNL full-chip cell in the provided layout."""
    return SqnlSingle.create(
        layout,
        name_chip="BASIC",
        with_grid=False,
        use_test_resonators=use_test_resonators,
        junction_type="Sim",
        name_mask="SQNL",
        name_copy=None,
        readout_res_lengths=[5000, 5100, 5200, 5300, 5400, 5500],
        test_res_lengths=[5200, 5400, 5600, 5800],
        n_fingers=[4, 4, 2, 4],
        l_fingers=[23.1, 9.9, 14.1, 10],
        type_coupler=["interdigital", "interdigital", "interdigital", "gap"],
    )


def get_cell_refpoints(cell):
    """Return the absolute refpoints for a built SQNL cell."""
    refpoint_layer = cell.layout().layer(default_layers["refpoints"])
    return get_refpoints(refpoint_layer, cell, rec_levels=None)


def build_simulation_from_sqnl_cell(cell, launchers=False, name="sqnl_full_chip_sim"):
    """Wrap the built SQNL cell into a generic simulation object."""
    simulation = EmptySimulation.from_cell(
        cell,
        margin=0,
        name=name,
        use_ports=True,
        use_internal_ports=True,
        port_size=900 if launchers else 200,
    )
    if not launchers:
        simulation.box &= pya.DBox(pya.DPoint(800, 800), pya.DPoint(9200, 9200))
    else:
        simulation.box &= pya.DBox(pya.DPoint(200, 200), pya.DPoint(9800, 9800))
    return simulation


def add_sqnl_ports(simulation, refpoints, launchers=False):
    """Add edge and internal ports using the SQNL launcher and qubit refpoints."""
    port_shift = 600 if launchers else 0
    launcher_shifts = {
        "NW": [0, port_shift],
        "WN": [-port_shift, 0],
        "WS": [-port_shift, 0],
        "SW": [0, -port_shift],
        "SE": [0, -port_shift],
        "ES": [port_shift, 0],
        "EN": [port_shift, 0],
        "NE": [0, port_shift],
    }
    for index, launcher_name in enumerate(LAUNCHER_NAMES, start=1):
        simulation.ports.append(
            EdgePort(index, refpoints[f"{launcher_name}_port"] + pya.DVector(*launcher_shifts[launcher_name]))
        )

    for qubit_index in range(6):
        simulation.ports.append(
            InternalPort(
                qubit_index + 9,
                *simulation.etched_line(
                    refpoints[f"qb_{qubit_index}_port_squid_a"],
                    refpoints[f"qb_{qubit_index}_port_squid_b"],
                ),
            )
        )


def run_smoke_check(simulation, refpoints, export_path):
    """Assert the expected SQNL geometry, ports, and exported batch artifacts."""
    for launcher_name in LAUNCHER_NAMES:
        assert f"{launcher_name}_port" in refpoints, f"Missing launcher refpoint: {launcher_name}_port"

    for qubit_index in range(6):
        assert f"qb_{qubit_index}_port_squid_a" in refpoints
        assert f"qb_{qubit_index}_port_squid_b" in refpoints

    edge_ports = [port for port in simulation.ports if isinstance(port, EdgePort)]
    internal_ports = [port for port in simulation.ports if isinstance(port, InternalPort)]
    assert len(edge_ports) == 8, f"Expected 8 edge ports, found {len(edge_ports)}"
    assert len(internal_ports) == 6, f"Expected 6 internal ports, found {len(internal_ports)}"

    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat"
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas"
    assert (export_path / SIMULATION_BATCH_FILENAME).exists(), "Missing simulation_batch.json"
    assert any(path.suffix == ".json" and path.name != SIMULATION_BATCH_FILENAME for path in export_path.iterdir())


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ansys-tool", choices=("hfss", "q3d"), default="hfss")
    parser.add_argument("--launchers", action="store_true", help="Include launcher pads in the port sizing setup")
    parser.add_argument("--use-test-resonators", action="store_true", help="Build the test-resonator feedline variant")
    parser.add_argument("--export-dir", type=Path, help="Export directory. Defaults to tmp/<script>_<tool>")
    parser.add_argument("--smoke-check", action="store_true", help="Run local assertions on geometry and artifacts")
    parser.add_argument("--open-oas", action="store_true", help="Open exported OAS in KLayout or the default app")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    export_path = (
        args.export_dir
        if args.export_dir is not None
        else create_or_empty_tmp_directory(Path(__file__).stem + f"_{args.ansys_tool}")
    )
    if args.export_dir is not None:
        export_path.mkdir(parents=True, exist_ok=True)

    layout = pya.Layout()
    cell = build_sqnl_cell(layout, use_test_resonators=args.use_test_resonators)
    refpoints = get_cell_refpoints(cell)
    simulation = build_simulation_from_sqnl_cell(cell, launchers=args.launchers)
    add_sqnl_ports(simulation, refpoints, launchers=args.launchers)

    oas = export_simulation_oas([simulation], export_path)
    export_parameters = {
        "ansys_tool": args.ansys_tool,
        "path": export_path,
        "exit_after_run": False,
    }
    if args.ansys_tool == "hfss":
        export_parameters.update(
            {
                "frequency": [5.0],
                "max_delta_s": 0.001,
                "sweep_start": 1.0,
                "sweep_end": 10.0,
                "sweep_count": 1001,
                "maximum_passes": 20,
            }
        )
    else:
        export_parameters.update(
            {
                "percent_error": 0.2,
                "maximum_passes": 18,
                "minimum_passes": 2,
                "minimum_converged_passes": 2,
            }
        )

    export_ansys([simulation], **export_parameters)
    configure_ansys_batch(export_path, [simulation], args.ansys_tool)

    if args.smoke_check:
        run_smoke_check(simulation, refpoints, export_path)
        alternate_cell = build_sqnl_cell(pya.Layout(), use_test_resonators=not args.use_test_resonators)
        alternate_refpoints = get_cell_refpoints(alternate_cell)
        assert "WN_port" in alternate_refpoints and "ES_port" in alternate_refpoints

    if args.open_oas:
        open_with_klayout_or_default_application(oas)

    logging.info("Exported SQNL full-chip simulation to %s", export_path)


if __name__ == "__main__":
    main()
