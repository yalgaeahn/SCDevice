"""HFSS S-parameter export for the SQNL chip v1 in-situ readout resonator."""

import argparse
import contextlib
import json
import logging
import math
import sys
from pathlib import Path

from kqcircuits.defaults import default_layers
from kqcircuits.elements.element import get_refpoints
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.empty_simulation import EmptySimulation
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.port import EdgePort, InternalPort
from kqcircuits.simulations.post_process import PostProcess

from scdevice_pcells.chips.sqnl_chip_v1 import SqnlSingle
from scdevice_pcells.junctions import SQNL_DIRECT_LEAD_SIM
from scdevice_pcells.simulations.export_paths import (
    add_kq_post_process_tool_metadata,
    create_or_empty_scdevice_tmp_directory,
    make_simulation_bat_location_independent,
)


def chip_default(name):
    return SqnlSingle.get_schema()[name].default


def first_chip_default(name):
    value = chip_default(name)
    return value[0] if isinstance(value, list) else value


class FeedlineSParameterSimulation(EmptySimulation):
    """EmptySimulation variant that adds feedline ports before layer splitting."""

    def build(self):
        feedline_y = chip_default("feedline_y")
        self.ports.append(EdgePort(1, pya.DPoint(self.box.left, feedline_y)))
        self.ports.append(EdgePort(2, pya.DPoint(self.box.right, feedline_y)))
        self.refpoints["crop_port_1"] = self.ports[0].signal_location
        self.refpoints["crop_port_2"] = self.ports[1].signal_location


def format_value(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}".replace(".", "p").replace("-", "m")


def parse_values(value):
    """Parse a single value, comma list, or inclusive start:stop:step range."""
    if ":" not in value:
        values = [float(part.strip()) for part in value.split(",") if part.strip()]
    else:
        parts = [float(part.strip()) for part in value.split(":")]
        if len(parts) != 3:
            raise ValueError("Range syntax must be start:stop:step.")
        start, stop, step = parts
        if step <= 0:
            raise ValueError("Range step must be positive.")
        if stop < start:
            raise ValueError("Range stop must be greater than or equal to start.")
        count = int(math.floor((stop - start) / step + 1e-12)) + 1
        values = [start + i * step for i in range(count)]

    if not values:
        raise ValueError("At least one sweep value is required.")
    return values


@contextlib.contextmanager
def suppress_from_cell_cell_warning():
    class FromCellCellWarningFilter(logging.Filter):
        def filter(self, record):
            return not record.getMessage().startswith(
                "Trying to set parameters which do not exist: {'cell'} for "
            )

    warning_filter = FromCellCellWarningFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(warning_filter)
    try:
        yield
    finally:
        root_logger.removeFilter(warning_filter)


def get_cell_refpoints(cell):
    refpoint_layer = cell.layout().layer(default_layers["refpoints"])
    return get_refpoints(refpoint_layer, cell, rec_levels=None)


def static_cell_for_simulation(cell):
    if cell.pcell_declaration() is None:
        return cell

    layout = cell.layout()
    return layout.cell(layout.convert_cell_to_static(cell.cell_index()))


def point_inside_box(point, box):
    return box.left <= point.x <= box.right and box.bottom <= point.y <= box.top


def build_sqnl_chip_v1_cell(layout, args, resonator_length, coupling_length, gap):
    readout_res_lengths = [resonator_length]
    readout_coupling_lengths = [coupling_length]
    cell = SqnlSingle.create(
        layout,
        name_chip="BASIC",
        with_grid=False,
        use_test_resonators=False,
        junction_type=SQNL_DIRECT_LEAD_SIM,
        name_mask="SQNL",
        name_copy=None,
        a=args.center_trace_width,
        b=args.gap_width,
        readout_res_lengths=readout_res_lengths,
        readout_coupling_lengths=readout_coupling_lengths,
        readout_feedline_gap=gap,
        readout_turn_radius=args.turn_radius,
        readout_meander_width=args.meander_width,
        feedline_y=chip_default("feedline_y"),
        feedline_x_distance=chip_default("feedline_x_distance"),
        use_readout_resonators=True,
        use_qubits=True,
    )
    return cell, readout_res_lengths, readout_coupling_lengths


def crop_box_for_chip_v1(refpoints, args):
    cplr = refpoints["qb_0_port_cplr"]
    base = refpoints["qb_0_base"]
    left = cplr.x - args.crop_half_width
    right = cplr.x + args.crop_half_width

    if left < refpoints["W_port"].x or right > refpoints["E_port"].x:
        raise ValueError("Crop x range must stay inside the straight W-E feedline segment.")

    feedline_y = chip_default("feedline_y")
    return pya.DBox(
        pya.DPoint(left, feedline_y - args.crop_feedline_margin),
        pya.DPoint(right, base.y + args.crop_qubit_margin),
    )


def make_readout_metadata(
    args,
    resonator_length,
    coupling_length,
    gap,
    readout_res_lengths,
    readout_coupling_lengths,
    crop_box,
):
    return {
        "resonator_index": 0,
        "resonator_length": resonator_length,
        "coupling_length": coupling_length,
        "feedline_resonator_gap": gap,
        "center_trace_width": args.center_trace_width,
        "gap_width": args.gap_width,
        "readout_res_lengths": readout_res_lengths,
        "readout_coupling_lengths": readout_coupling_lengths,
        "readout_short_type": "galvanic_term1_0",
        "crop_box": crop_box,
        "source_cell": "sqnl_chip_v1.SqnlSingle",
        "simulation_type": "in_situ_readout_feedline_2port_sparameter",
        "sim_junction_type": SQNL_DIRECT_LEAD_SIM,
        "circle_fit_included": False,
    }


def copy_relevant_refpoints(simulation, refpoints):
    for key in (
        "W_port",
        "E_port",
        "qb_0_port_cplr",
        "qb_0_base",
        "readout_0_short",
    ):
        if key in refpoints:
            simulation.refpoints[key] = refpoints[key]


def make_simulation(layout, args, resonator_length, coupling_length, gap):
    source_cell, readout_res_lengths, readout_coupling_lengths = build_sqnl_chip_v1_cell(
        layout,
        args,
        resonator_length,
        coupling_length,
        gap,
    )
    cell = static_cell_for_simulation(source_cell)
    refpoints = get_cell_refpoints(cell)
    crop_box = crop_box_for_chip_v1(refpoints, args)
    name = (
        f"sqnl_chip_v1_ro_s21_len_{format_value(resonator_length)}"
        f"_cpl_{format_value(coupling_length)}_gap_{format_value(gap)}"
    )
    metadata = make_readout_metadata(
        args,
        resonator_length,
        coupling_length,
        gap,
        readout_res_lengths,
        readout_coupling_lengths,
        crop_box,
    )
    simulation_kwargs = {
        "margin": 0,
        "box": crop_box,
        "ground_grid_box": crop_box,
        "name": name,
        "face_stack": ["1t1"],
        "use_ports": True,
        "port_size": args.port_size,
        "extra_json_data": metadata,
    }

    with suppress_from_cell_cell_warning():
        simulation = FeedlineSParameterSimulation.from_cell(cell, **simulation_kwargs)
    copy_relevant_refpoints(simulation, refpoints)
    return simulation


def make_simulations(layout, args):
    simulations = []
    for resonator_length in parse_values(args.lengths):
        for coupling_length in parse_values(args.coupling_lengths):
            for gap in parse_values(args.gaps):
                simulations.append(
                    make_simulation(layout, args, resonator_length, coupling_length, gap)
                )
    logging.info("Exporting %d HFSS S-parameter case(s).", len(simulations))
    return simulations


def load_exported_json(export_path, simulation):
    with open(export_path / f"{simulation.name}.json", "r", encoding="utf-8-sig") as file:
        return json.load(file)


def exported_setting(exported, name):
    return exported.get("analysis_setup", {}).get(
        name,
        exported.get("parameters", {}).get(name),
    )


def first_value(value):
    return value[0] if isinstance(value, list) else value


def run_smoke_check(simulations, export_path, args):
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas."
    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat."
    simulation_bat = (export_path / "simulation.bat").read_text(encoding="utf-8")
    assert ("calculate_q_from_s.py" in simulation_bat) == args.with_kq_port_q

    for simulation in simulations:
        exported = load_exported_json(export_path, simulation)
        assert exported["ansys_tool"] == "hfss"
        assert first_value(exported_setting(exported, "frequency")) == args.frequency
        assert exported_setting(exported, "sweep_start") == args.sweep_start
        assert exported_setting(exported, "sweep_end") == args.sweep_end
        assert exported_setting(exported, "sweep_count") == args.sweep_count
        assert exported_setting(exported, "sweep_type") == args.sweep_type
        assert exported_setting(exported, "max_delta_s") == args.max_delta_s
        assert exported_setting(exported, "maximum_passes") == args.maximum_passes
        expected_mesh_size = {} if args.gap_mesh_size is None else {"1t1_gap": args.gap_mesh_size}
        assert exported.get("mesh_size", {}) == expected_mesh_size

        ports = exported["ports"]
        assert len(ports) == 2, f"Expected exactly two feedline ports, got {len(ports)}."
        assert all(port["type"] == "EdgePort" for port in ports)
        assert not any(port["type"] == "InternalPort" for port in ports)
        assert not any(port.get("junction") for port in ports)

        edge_ports = [port for port in simulation.ports if isinstance(port, EdgePort)]
        internal_ports = [port for port in simulation.ports if isinstance(port, InternalPort)]
        assert len(edge_ports) == 2
        assert not internal_ports
        assert abs(edge_ports[0].signal_location.x - simulation.box.left) < 1e-9
        assert abs(edge_ports[1].signal_location.x - simulation.box.right) < 1e-9
        assert edge_ports[0].signal_location.y == chip_default("feedline_y")
        assert edge_ports[1].signal_location.y == chip_default("feedline_y")

        metadata = exported["parameters"]["extra_json_data"]
        assert metadata["source_cell"] == "sqnl_chip_v1.SqnlSingle"
        assert metadata["simulation_type"] == "in_situ_readout_feedline_2port_sparameter"
        assert metadata["circle_fit_included"] is False
        assert metadata["resonator_index"] == 0
        assert metadata["readout_res_lengths"][0] == metadata["resonator_length"]
        assert metadata["readout_coupling_lengths"][0] == metadata["coupling_length"]
        assert metadata["readout_short_type"] == "galvanic_term1_0"

        for key in ("qb_0_port_cplr", "qb_0_base", "readout_0_short"):
            assert key in simulation.refpoints, f"Missing refpoint: {key}."
            assert point_inside_box(simulation.refpoints[key], simulation.box)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lengths", default=str(first_chip_default("readout_res_lengths")))
    parser.add_argument("--coupling-lengths", default=str(first_chip_default("readout_coupling_lengths")))
    parser.add_argument("--gaps", default=str(chip_default("readout_feedline_gap")))
    parser.add_argument("--frequency", type=float, default=6.009)
    parser.add_argument("--sweep-start", type=float, default=5.99)
    parser.add_argument("--sweep-end", type=float, default=6.01)
    parser.add_argument("--sweep-count", type=int, default=5001)
    parser.add_argument("--sweep-type", choices=["interpolating", "discrete", "fast"], default="interpolating")
    parser.add_argument("--max-delta-s", type=float, default=0.01)
    parser.add_argument("--maximum-passes", type=int, default=10)
    parser.add_argument("--crop-half-width", type=float, default=1000)
    parser.add_argument("--crop-feedline-margin", type=float, default=500)
    parser.add_argument("--crop-qubit-margin", type=float, default=800)
    parser.add_argument("--center-trace-width", type=float, default=chip_default("a"))
    parser.add_argument("--gap-width", type=float, default=chip_default("b"))
    parser.add_argument("--gap-mesh-size", type=float, default=None)
    parser.add_argument("--turn-radius", type=float, default=chip_default("readout_turn_radius"))
    parser.add_argument("--meander-width", type=float, default=chip_default("readout_meander_width"))
    parser.add_argument("--port-size", type=float, default=200)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--with-kq-port-q", action="store_true")
    parser.add_argument("--smoke-check", action="store_true")
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    export_path = args.export_dir or create_or_empty_scdevice_tmp_directory(
        Path(__file__).stem + "_hfss"
    )
    export_path.mkdir(parents=True, exist_ok=True)

    layout = pya.Layout()
    simulations = make_simulations(layout, args)
    export_simulation_oas(simulations, export_path)
    export_ansys(
        simulations,
        ansys_tool="hfss",
        path=export_path,
        exit_after_run=False,
        frequency=[args.frequency],
        max_delta_s=args.max_delta_s,
        sweep_start=args.sweep_start,
        sweep_end=args.sweep_end,
        sweep_count=args.sweep_count,
        sweep_type=args.sweep_type,
        maximum_passes=args.maximum_passes,
        mesh_size={} if args.gap_mesh_size is None else {"1t1_gap": args.gap_mesh_size},
        post_process=PostProcess("calculate_q_from_s.py") if args.with_kq_port_q else None,
    )
    if args.with_kq_port_q:
        add_kq_post_process_tool_metadata(export_path)
    make_simulation_bat_location_independent(export_path)

    if args.smoke_check:
        run_smoke_check(simulations, export_path, args)


if __name__ == "__main__":
    main()
