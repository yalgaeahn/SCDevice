"""Eigenmode export workflow for a single DoublePadsSQNL qubit."""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from kqcircuits.defaults import default_faces
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.post_process import PostProcess
from kqcircuits.simulations.single_element_simulation import (
    get_single_element_sim_class,
)
from kqcircuits.util.export_helper import open_with_klayout_or_default_application

from scdevice_pcells.junctions import SQNL_DIRECT_LEAD_SIM
from scdevice_pcells.junctions.direct_lead_sim import (
    DIRECT_LEAD_ATTACH_SPAN_UM,
    SURROGATE_PAD_LENGTH_UM,
    SURROGATE_PAD_WIDTH_UM,
)
from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL
from scdevice_pcells.simulations.double_pads_sqnl_capacitance import (
    case_name,
    get_cases,
)
from scdevice_pcells.simulations.export_paths import (
    create_or_empty_scdevice_tmp_directory,
    make_simulation_bat_location_independent,
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

CASE_CSV = "eigenmode_cases.csv"
MODES = ("fast", "pyepr")

EIGENMODE_DEFAULTS = {
    "fast": {
        "n_modes": 1,
        "min_frequency": 0.5,
        "max_delta_f": 0.05,
        "mesh_gap": 50,
        "maximum_passes": 8,
        "minimum_passes": 1,
        "minimum_converged_passes": 1,
        "simulation_flags": [],
    },
    "pyepr": {
        "n_modes": 1,
        "min_frequency": 0.5,
        "max_delta_f": 0.008,
        "mesh_gap": 25,
        "maximum_passes": 17,
        "minimum_passes": 1,
        "minimum_converged_passes": 2,
        "simulation_flags": ["pyepr"],
    },
}


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
        "target_room_temperature_resistance_ohm": (
            ROOM_TEMPERATURE_RESISTANCE_TARGET_OHM
        ),
        "junction_inductance_nH": JUNCTION_INDUCTANCE_H / 1e-9,
        "junction_capacitance_fF": junction_capacitance_ff,
        "sim_junction_type": SQNL_DIRECT_LEAD_SIM,
        "direct_lead_attach_span_um": DIRECT_LEAD_ATTACH_SPAN_UM,
        "surrogate_pad_width_um": SURROGATE_PAD_WIDTH_UM,
        "surrogate_pad_length_um": SURROGATE_PAD_LENGTH_UM,
    }


def simulation_parameters(case, args, index, mode):
    name = case_name(case, f"dpse{args.sweep[0]}{index:03d}_{mode}")
    geometry = {key: float(value) for key, value in case.items()}
    parameters = {
        "name": name,
        "box": pya.DBox(pya.DPoint(0, 0), pya.DPoint(3000, 3000)),
        "face_stack": ["1t1"],
        "use_internal_ports": True,
        "use_ports": True,
        "waveguide_length": 200,
        "junction_inductance": JUNCTION_INDUCTANCE_H,
        "junction_capacitance": args.junction_capacitance_ff * 1e-15,
        "ground_gap": [case["ground_gap_width_um"], case["ground_gap_height_um"]],
        "a": 5,
        "b": 20,
        "coupler_a": case["coupler_a_um"],
        "coupler_extent": [case["coupler_width_um"], case["coupler_height_um"]],
        "coupler_offset": case["coupler_offset_um"],
        "island1_extent": [case["width_um"], case["height_um"]],
        "island2_extent": [case["width_um"], case["height_um"]],
        "island_island_gap": case["island_island_gap_um"],
        "island1_taper_width": case["taper_width_um"],
        "island2_taper_width": case["taper_width_um"],
        "island1_taper_junction_width": case["taper_junction_width_um"],
        "island2_taper_junction_width": case["taper_junction_width_um"],
        "extra_json_data": {
            "eigenmode_geometry": geometry,
            "eigenmode_mode": mode,
            **target_metadata(args.junction_capacitance_ff),
        },
    }
    if mode == "pyepr":
        parameters.update(
            {
                "tls_layer_thickness": 5e-3,
                "tls_sheet_approximation": True,
            }
        )
    return parameters


def make_simulations(layout, args, mode):
    sim_class = get_single_element_sim_class(
        DoublePadsSQNL,
        sim_junction_type=SQNL_DIRECT_LEAD_SIM,
    )
    simulations = []
    for index, case in enumerate(get_cases(args)):
        simulations.append(
            sim_class(layout, **simulation_parameters(case, args, index, mode))
        )
    logging.info(
        "Prepared %d DoublePadsSQNL eigenmode %s simulation case(s).",
        len(simulations),
        mode,
    )
    return simulations


def write_rows_csv(path, rows):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_case_metadata(simulations, export_path):
    rows = []
    for simulation in simulations:
        metadata = simulation.extra_json_data
        geometry = metadata["eigenmode_geometry"]
        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        rows.append(
            {
                "name": simulation.name,
                "mode": metadata["eigenmode_mode"],
                **geometry,
                "junction_attach_1_x_um": upper.x,
                "junction_attach_1_y_um": upper.y,
                "junction_attach_2_x_um": lower.x,
                "junction_attach_2_y_um": lower.y,
                "junction_attach_span_um": upper.y - lower.y,
                "junction_inductance_nH": metadata["junction_inductance_nH"],
                "junction_capacitance_fF": metadata["junction_capacitance_fF"],
            }
        )
    write_rows_csv(export_path / CASE_CSV, rows)


def selected_modes(args):
    return MODES if args.mode == "both" else (args.mode,)


def prepare_export_path(args, mode):
    if args.export_dir:
        path = args.export_dir / mode if args.mode == "both" else args.export_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    return create_or_empty_scdevice_tmp_directory(
        f"{Path(__file__).stem}_{mode}_{args.sweep}"
    )


def export_mode(simulations, export_path, args, mode):
    settings = EIGENMODE_DEFAULTS[mode]
    oas = export_simulation_oas(simulations, export_path)
    write_case_metadata(simulations, export_path)
    export_ansys(
        simulations,
        ansys_tool="eigenmode",
        path=export_path,
        exit_after_run=True,
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
    return oas


def load_exported_json(export_path, simulation):
    with open(
        export_path / f"{simulation.name}.json", "r", encoding="utf-8-sig"
    ) as file:
        return json.load(file)


def first_value(value):
    if isinstance(value, list):
        return value[0]
    return value


def assert_base_metal_addition_present(simulation):
    layer_info = default_faces["1t1"]["base_metal_addition"]
    layer_index = simulation.layout.layer(layer_info)
    region = pya.Region(simulation.cell.begin_shapes_rec(layer_index))
    assert (
        not region.is_empty()
    ), "base_metal_addition must contain surrogate pads for direct lead sim."


def run_smoke_check(simulations, export_path, mode):
    assert simulations, "No simulations were created."
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas."
    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat."
    assert (export_path / CASE_CSV).exists(), f"Missing {CASE_CSV}."

    settings = EIGENMODE_DEFAULTS[mode]
    bat_text = (export_path / "simulation.bat").read_text(encoding="utf-8")
    assert ("run_pyepr_t1_estimate.py" in bat_text) == (mode == "pyepr")

    for simulation in simulations:
        exported = load_exported_json(export_path, simulation)
        parameters = exported["parameters"]
        analysis_setup = exported["analysis_setup"]
        flags = exported.get("simulation_flags") or parameters.get("simulation_flags")
        flags = [] if flags is None else flags

        assert exported["ansys_tool"] == "eigenmode"
        assert analysis_setup["n_modes"] == settings["n_modes"]
        assert analysis_setup["min_frequency"] == settings["min_frequency"]
        assert analysis_setup["max_delta_f"] == settings["max_delta_f"]
        assert exported["mesh_size"] == {"1t1_gap": settings["mesh_gap"]}
        assert flags == settings["simulation_flags"]

        tls_thickness = first_value(parameters.get("tls_layer_thickness", [0.0]))
        if mode == "pyepr":
            assert parameters["tls_sheet_approximation"] is True
            assert abs(tls_thickness - 5e-3) < 1e-12
        else:
            assert parameters["tls_sheet_approximation"] is False
            assert abs(tls_thickness) < 1e-12

        metadata = parameters["extra_json_data"]
        assert metadata["eigenmode_mode"] == mode
        assert metadata["target_source"] == TARGET_SOURCE
        assert metadata["target_C_sigma_fF"] == C_SIGMA_TARGET_FF

        junction_ports = [port for port in exported["ports"] if port["junction"]]
        assert junction_ports, "Missing junction internal port."
        for port in junction_ports:
            assert abs(port["inductance"] - JUNCTION_INDUCTANCE_H) < 1e-15

        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        center = simulation.box.center()
        midpoint_y = (upper.y + lower.y) / 2
        assert abs(upper.x - center.x) < 1e-6
        assert abs(lower.x - center.x) < 1e-6
        assert abs(midpoint_y - (center.y + simulation.squid_offset)) < 1e-6
        assert abs((upper.y - lower.y) - DIRECT_LEAD_ATTACH_SPAN_UM) < 1e-3
        assert_base_metal_addition_present(simulation)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fast", "pyepr", "both"], default="both")
    parser.add_argument(
        "--sweep", choices=["single", "coarse", "refine"], default="single"
    )
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--smoke-check", action="store_true")
    parser.add_argument("--open-oas", action="store_true")
    parser.add_argument("--junction-capacitance-ff", type=float, default=0.1)
    parser.add_argument("--refine-source", type=Path)
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logging.info(
        "Target from %s: fge=%.5f GHz, C_sigma=%.4f fF, LJ=%.5f nH.",
        TARGET_SOURCE,
        F_GE_TARGET_GHZ,
        C_SIGMA_TARGET_FF,
        JUNCTION_INDUCTANCE_H / 1e-9,
    )

    exported_oas = []
    for mode in selected_modes(args):
        export_path = prepare_export_path(args, mode)
        layout = pya.Layout()
        simulations = make_simulations(layout, args, mode)
        oas = export_mode(simulations, export_path, args, mode)
        exported_oas.append(oas)
        if args.smoke_check:
            run_smoke_check(simulations, export_path, mode)

    if args.open_oas:
        for oas in exported_oas:
            open_with_klayout_or_default_application(oas)


if __name__ == "__main__":
    main()
