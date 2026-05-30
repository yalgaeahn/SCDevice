"""Eigenmode export for an SQNL chip v2 qubit/readout/feedline crop."""

import argparse
import json
import logging
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

from scdevice_pcells.chips.sqnl_chip_v2 import SqnlSingleV2 as SqnlSingle
from scdevice_pcells.chips.sqnl_chip_v2 import V1_QUBIT_SPACING_Y, V2_QUBIT_SPACING_Y
from scdevice_pcells.junctions import SQNL_DIRECT_LEAD_SIM
from scdevice_pcells.junctions.direct_lead_sim import (
    DIRECT_LEAD_ATTACH_SPAN_UM,
    JUNCTION_TERMINAL_MODEL,
    SURROGATE_PADS_ENABLED,
)
from scdevice_pcells.simulations.export_paths import (
    create_or_empty_scdevice_tmp_directory,
    make_simulation_bat_location_independent,
)
from scdevice_pcells.simulations.sqnl_readout_resonator_common import (
    format_value,
    point_inside_box,
    suppress_from_cell_cell_warning,
)
from scdevice_pcells.simulations.transmon_targets import (
    ANHARMONICITY_TARGET_GHZ,
    C_SIGMA_TARGET_FF,
    EC_TARGET_GHZ,
    EJ_EC_TARGET_RATIO,
    EJ_TARGET_GHZ,
    F_EF_TARGET_GHZ,
    F_GE_TARGET_GHZ,
    F_GF_OVER_2_TARGET_GHZ,
    IC_TARGET_NA,
    JUNCTION_INDUCTANCE_H,
    ROOM_TEMPERATURE_RESISTANCE_TARGET_OHM,
    TARGET_SOURCE,
    TARGET_URL,
)

MODES = ("fast", "pyepr")

EIGENMODE_DEFAULTS = {
    "fast": {
        "min_frequency": 3.5,
        "n_modes": 3,
        "max_delta_f": 0.05,
        "maximum_passes": 6,
        "minimum_passes": 1,
        "minimum_converged_passes": 1,
        "mesh_gap": 30,
        "simulation_flags": [],
    },
    "pyepr": {
        "min_frequency": 4.5,
        "n_modes": 2,
        "max_delta_f": 0.01,
        "maximum_passes": 9,
        "minimum_passes": 1,
        "minimum_converged_passes": 1,
        "mesh_gap": 30,
        "simulation_flags": ["pyepr"],
    },
}
SETTING_OVERRIDES = (
    "min_frequency",
    "n_modes",
    "max_delta_f",
    "maximum_passes",
    "minimum_passes",
    "minimum_converged_passes",
    "mesh_gap",
)
JUNCTION_REFPOINT_CANDIDATES = (
    ("qb_0_squid_port_squid_a", "qb_0_squid_port_squid_b"),
    ("qb_0_port_squid_a", "qb_0_port_squid_b"),
    ("squid_port_squid_a", "squid_port_squid_b"),
    ("port_squid_a", "port_squid_b"),
    ("qb_0_junction_attach_island_1", "qb_0_junction_attach_island_2"),
    ("junction_attach_island_1", "junction_attach_island_2"),
)


def chip_default(name):
    return SqnlSingle.get_schema()[name].default


def first_chip_default(name):
    value = chip_default(name)
    return value[0] if isinstance(value, list) else value


def pyepr_post_process():
    return PostProcess(
        "run_pyepr_t1_estimate.py",
        repeat_for_each=True,
        substrate_loss_tangent=5e-7,
        dielectric_surfaces={
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
    )


def target_metadata(junction_capacitance_ff):
    return {
        "target_source": TARGET_SOURCE,
        "target_url": TARGET_URL,
        "target_Ec_GHz": EC_TARGET_GHZ,
        "target_EJ_GHz": EJ_TARGET_GHZ,
        "target_EJ_EC_ratio": EJ_EC_TARGET_RATIO,
        "target_C_sigma_fF": C_SIGMA_TARGET_FF,
        "target_fge_GHz": F_GE_TARGET_GHZ,
        "target_fef_GHz": F_EF_TARGET_GHZ,
        "target_fgf_over_2_GHz": F_GF_OVER_2_TARGET_GHZ,
        "target_anharmonicity_GHz": ANHARMONICITY_TARGET_GHZ,
        "target_Ic_nA": IC_TARGET_NA,
        "target_room_temperature_resistance_ohm": ROOM_TEMPERATURE_RESISTANCE_TARGET_OHM,
        "junction_inductance_nH": JUNCTION_INDUCTANCE_H / 1e-9,
        "junction_capacitance_fF": junction_capacitance_ff,
        "sim_junction_type": SQNL_DIRECT_LEAD_SIM,
        "direct_lead_attach_span_um": DIRECT_LEAD_ATTACH_SPAN_UM,
        "junction_terminal_model": JUNCTION_TERMINAL_MODEL,
        "surrogate_pads_enabled": SURROGATE_PADS_ENABLED,
        "surrogate_pad_width_um": 0.0,
        "surrogate_pad_length_um": 0.0,
    }


def selected_modes(args):
    return MODES if args.mode == "both" else (args.mode,)


def mode_settings(args, mode):
    settings = dict(EIGENMODE_DEFAULTS[mode])
    for key in SETTING_OVERRIDES:
        value = getattr(args, key)
        if value is not None:
            settings[key] = value
    return settings


def prepare_export_path(args, mode):
    if args.export_dir:
        path = args.export_dir / mode if args.mode == "both" else args.export_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    return create_or_empty_scdevice_tmp_directory(
        f"{Path(__file__).stem}_{mode}_eigenmode"
    )


def get_cell_refpoints(cell):
    refpoint_layer = cell.layout().layer(default_layers["refpoints"])
    return get_refpoints(refpoint_layer, cell, rec_levels=None)


def static_cell_for_simulation(cell):
    if cell.pcell_declaration() is None:
        return cell

    layout = cell.layout()
    return layout.cell(layout.convert_cell_to_static(cell.cell_index()))


def selected_readout_parameters(args):
    selected_length = first_chip_default("readout_res_lengths")
    return selected_length, [selected_length], [args.coupling_length]


def build_sqnl_chip_v2_cell(layout, args):
    selected_length, readout_res_lengths, readout_coupling_lengths = (
        selected_readout_parameters(args)
    )
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
        readout_feedline_gap=args.gap,
        readout_turn_radius=args.turn_radius,
        readout_meander_width=args.meander_width,
        feedline_y=chip_default("feedline_y"),
        feedline_x_distance=chip_default("feedline_x_distance"),
        use_readout_resonators=True,
        use_qubits=True,
        use_feedline=args.use_feedline,
    )
    return cell, selected_length, readout_res_lengths, readout_coupling_lengths


def crop_box_for_chip_v2(refpoints, args):
    cplr = refpoints["qb_0_port_cplr"]
    base = refpoints["qb_0_base"]
    readout_short = refpoints.get("readout_0_short", cplr)
    readout_margin = max(args.crop_readout_margin, args.meander_width / 2 + args.turn_radius)

    left = min(cplr.x - args.crop_half_width, readout_short.x - readout_margin)
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
    mode,
    resonator_length,
    readout_res_lengths,
    readout_coupling_lengths,
    crop_box,
):
    return {
        "resonator_index": 0,
        "resonator_length": resonator_length,
        "coupling_length": args.coupling_length,
        "feedline_resonator_gap": args.gap,
        "use_feedline": args.use_feedline,
        "center_trace_width": args.center_trace_width,
        "gap_width": args.gap_width,
        "readout_res_lengths": readout_res_lengths,
        "readout_coupling_lengths": readout_coupling_lengths,
        "readout_short_type": "galvanic_term2_0",
        "crop_box": crop_box,
        "source_cell": "sqnl_chip_v2.SqnlSingleV2",
        "eigenmode_mode": mode,
        "qubit_spacing_y": V2_QUBIT_SPACING_Y,
        **target_metadata(args.junction_capacitance_ff),
    }


def find_junction_refpoints(refpoints):
    for signal_key, ground_key in JUNCTION_REFPOINT_CANDIDATES:
        if signal_key in refpoints and ground_key in refpoints:
            return signal_key, ground_key
    available = ", ".join(sorted(key for key in refpoints if "squid" in key or "junction" in key))
    raise KeyError(
        "Could not find SQNL junction refpoints. "
        f"Available junction-like refpoints: {available}"
    )


def add_junction_internal_port(simulation, refpoints, args):
    signal_key, ground_key = find_junction_refpoints(refpoints)
    signal, ground = simulation.etched_line(refpoints[signal_key], refpoints[ground_key])
    simulation.ports.append(
        InternalPort(
            1,
            signal,
            ground,
            inductance=JUNCTION_INDUCTANCE_H,
            capacitance=args.junction_capacitance_ff * 1e-15,
            junction=True,
            floating=True,
        )
    )
    for key in (signal_key, ground_key):
        simulation.refpoints[key] = refpoints[key]
    simulation.extra_json_data["junction_refpoints"] = [signal_key, ground_key]


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


def make_simulation(layout, args, mode):
    source_cell, selected_length, readout_res_lengths, readout_coupling_lengths = (
        build_sqnl_chip_v2_cell(layout, args)
    )
    cell = static_cell_for_simulation(source_cell)
    refpoints = get_cell_refpoints(cell)
    crop_box = crop_box_for_chip_v2(refpoints, args)
    feedline_suffix = "" if args.use_feedline else "_nofeedline"
    name = (
        f"sqnl_chip_v2_eigen_{mode}_len_{format_value(selected_length)}"
        f"_cpl_{format_value(args.coupling_length)}_gap_{format_value(args.gap)}"
        f"{feedline_suffix}"
    )
    metadata = make_readout_metadata(
        args,
        mode,
        selected_length,
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
        "extra_json_data": metadata,
    }
    if mode == "pyepr":
        simulation_kwargs.update(
            {
                "tls_layer_thickness": 5e-3,
                "tls_sheet_approximation": True,
            }
        )

    with suppress_from_cell_cell_warning():
        simulation = EmptySimulation.from_cell(cell, **simulation_kwargs)
    copy_relevant_refpoints(simulation, refpoints)
    add_junction_internal_port(simulation, refpoints, args)
    return simulation


def load_exported_json(export_path, simulation):
    with open(export_path / f"{simulation.name}.json", "r", encoding="utf-8-sig") as file:
        return json.load(file)


def first_value(value):
    if isinstance(value, list):
        return value[0]
    return value


def exported_setting(exported, name):
    return exported.get("analysis_setup", {}).get(
        name, exported.get("parameters", {}).get(name)
    )


def recursive_shape_count(cell, layer_index):
    return sum(1 for _ in cell.begin_shapes_rec(layer_index))


def exported_gds_layer_counts(export_path, exported):
    gds_path = export_path / exported["gds_file"]
    assert gds_path.exists(), f"Missing exported GDS: {gds_path.name}."
    assert gds_path.stat().st_size > 66, f"Exported GDS is empty: {gds_path.name}."

    gds_layout = pya.Layout()
    gds_layout.read(str(gds_path))
    top_cells = list(gds_layout.top_cells())
    assert top_cells, f"Exported GDS has no top cells: {gds_path.name}."

    counts = {}
    for layer_name, layer_data in exported["layers"].items():
        layer_number = layer_data.get("layer")
        if layer_number is None:
            continue
        layer_index = gds_layout.layer(pya.LayerInfo(int(layer_number), 0))
        counts[layer_name] = sum(recursive_shape_count(top, layer_index) for top in top_cells)
    return counts


def run_smoke_check(simulation, export_path, mode, settings, args):
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas."
    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat."
    simulation_bat = (export_path / "simulation.bat").read_text(encoding="utf-8")
    assert ("run_pyepr_t1_estimate.py" in simulation_bat) == (mode == "pyepr")
    if mode == "pyepr":
        assert "python_sitecustomize" in simulation_bat

    exported = load_exported_json(export_path, simulation)
    assert exported["ansys_tool"] == "eigenmode"
    assert exported_setting(exported, "n_modes") == settings["n_modes"]
    assert exported_setting(exported, "min_frequency") == settings["min_frequency"]
    assert exported_setting(exported, "max_delta_f") == settings["max_delta_f"]
    assert exported.get("mesh_size", exported["parameters"].get("mesh_size")) == {
        "1t1_gap": settings["mesh_gap"]
    }
    flags = exported.get("simulation_flags") or exported["parameters"].get("simulation_flags")
    assert ([] if flags is None else flags) == settings["simulation_flags"]
    gds_layer_counts = exported_gds_layer_counts(export_path, exported)
    missing_layers = [
        layer_name
        for layer_name in ("1t1_signal_1", "1t1_signal_2", "1t1_gap", "1t1_ground")
        if gds_layer_counts.get(layer_name, 0) == 0
    ]
    assert not missing_layers, f"Exported GDS has no shapes on layers: {missing_layers}."

    ports = exported["ports"]
    assert len(ports) == 1, f"Expected only one junction port, got {len(ports)}."
    assert ports[0]["type"] == "InternalPort"
    assert ports[0]["junction"] is True
    assert abs(ports[0]["inductance"] - JUNCTION_INDUCTANCE_H) < 1e-15
    assert not any(port["type"] == "EdgePort" for port in ports)

    parameters = exported["parameters"]
    tls_thickness = first_value(parameters.get("tls_layer_thickness", [0.0]))
    if mode == "pyepr":
        assert parameters["tls_sheet_approximation"] is True
        assert abs(tls_thickness - 5e-3) < 1e-12
    else:
        assert parameters["tls_sheet_approximation"] is False
        assert abs(tls_thickness) < 1e-12

    metadata = parameters["extra_json_data"]
    assert metadata["source_cell"] == "sqnl_chip_v2.SqnlSingleV2"
    assert metadata["eigenmode_mode"] == mode
    assert metadata["use_feedline"] == args.use_feedline
    assert metadata["resonator_length"] == first_chip_default("readout_res_lengths")
    assert metadata["readout_res_lengths"][0] == first_chip_default("readout_res_lengths")
    assert metadata["readout_short_type"] == "galvanic_term2_0"
    assert metadata["qubit_spacing_y"] == V2_QUBIT_SPACING_Y
    assert metadata["sim_junction_type"] == SQNL_DIRECT_LEAD_SIM
    assert metadata["junction_terminal_model"] == JUNCTION_TERMINAL_MODEL
    assert metadata["surrogate_pads_enabled"] is False

    for key in ("qb_0_base", "qb_0_port_cplr", "readout_0_short"):
        assert point_inside_box(simulation.refpoints[key], simulation.box)
    for key in simulation.extra_json_data["junction_refpoints"]:
        assert point_inside_box(simulation.refpoints[key], simulation.box)

    assert simulation.refpoints["readout_0_short"].x < simulation.refpoints["qb_0_port_cplr"].x
    assert simulation.refpoints["readout_0_short"].y < simulation.refpoints["qb_0_port_cplr"].y
    qubit_lift = (V2_QUBIT_SPACING_Y - V1_QUBIT_SPACING_Y) / 2
    assert abs(
        simulation.refpoints["qb_0_port_cplr"].y
        - simulation.refpoints["readout_0_short"].y
        - qubit_lift
    ) < 1e-9
    assert abs(
        simulation.refpoints[simulation.extra_json_data["junction_refpoints"][0]].distance(
            simulation.refpoints[simulation.extra_json_data["junction_refpoints"][1]]
        )
        - DIRECT_LEAD_ATTACH_SPAN_UM
    ) < 1e-3
    assert not any(isinstance(port, EdgePort) for port in simulation.ports)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fast", "pyepr", "both"], default="pyepr")
    parser.add_argument("--coupling-length", type=float, default=first_chip_default("readout_coupling_lengths"))
    parser.add_argument("--gap", type=float, default=chip_default("readout_feedline_gap"))
    parser.add_argument("--turn-radius", type=float, default=chip_default("readout_turn_radius"))
    parser.add_argument("--meander-width", type=float, default=chip_default("readout_meander_width"))
    parser.add_argument("--crop-half-width", type=float, default=1000)
    parser.add_argument("--crop-readout-margin", type=float, default=700)
    parser.add_argument("--crop-feedline-margin", type=float, default=500)
    parser.add_argument("--crop-qubit-margin", type=float, default=800)
    parser.add_argument("--center-trace-width", type=float, default=chip_default("a"))
    parser.add_argument("--gap-width", type=float, default=chip_default("b"))
    parser.add_argument("--junction-capacitance-ff", type=float, default=0.1)
    parser.add_argument("--min-frequency", type=float)
    parser.add_argument("--n-modes", type=int)
    parser.add_argument("--max-delta-f", type=float)
    parser.add_argument("--maximum-passes", type=int)
    parser.add_argument("--minimum-passes", type=int)
    parser.add_argument("--minimum-converged-passes", type=int)
    parser.add_argument("--mesh-gap", type=float)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--no-feedline", dest="use_feedline", action="store_false")
    parser.set_defaults(use_feedline=True)
    parser.add_argument("--smoke-check", action="store_true")
    return parser.parse_known_args()[0]


def export_mode(args, mode):
    settings = mode_settings(args, mode)
    export_path = prepare_export_path(args, mode)
    layout = pya.Layout()
    simulation = make_simulation(layout, args, mode)
    export_simulation_oas([simulation], export_path)
    export_ansys(
        [simulation],
        ansys_tool="eigenmode",
        path=export_path,
        exit_after_run=False,
        min_frequency=settings["min_frequency"],
        max_delta_f=settings["max_delta_f"],
        n_modes=settings["n_modes"],
        mesh_size={"1t1_gap": settings["mesh_gap"]},
        maximum_passes=settings["maximum_passes"],
        minimum_passes=settings["minimum_passes"],
        minimum_converged_passes=settings["minimum_converged_passes"],
        simulation_flags=settings["simulation_flags"],
        post_process=pyepr_post_process() if mode == "pyepr" else None,
    )
    make_simulation_bat_location_independent(export_path)

    if args.smoke_check:
        run_smoke_check(simulation, export_path, mode, settings, args)


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    for mode in selected_modes(args):
        export_mode(args, mode)


if __name__ == "__main__":
    main()
