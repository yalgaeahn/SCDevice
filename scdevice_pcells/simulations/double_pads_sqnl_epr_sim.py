"""Ansys MER-corrected EPR export workflow for a single DoublePadsSQNL qubit."""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.ansys.ansys_solution import AnsysEigenmodeSolution
from kqcircuits.simulations.export.cross_section.epr_correction_export import get_epr_correction_simulations
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.post_process import PostProcess
from kqcircuits.simulations.single_element_simulation import get_single_element_sim_class
from kqcircuits.util.export_helper import open_with_klayout_or_default_application

from scdevice_pcells.junctions import SQNL_DIRECT_LEAD_SIM
from scdevice_pcells.junctions.direct_lead_sim import (
    DIRECT_LEAD_ATTACH_SPAN_UM,
    JUNCTION_TERMINAL_MODEL,
    SURROGATE_PADS_ENABLED,
)
from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL
from scdevice_pcells.simulations.double_pads_sqnl_capacitance import (
    assert_direct_taper_junction_port,
    case_name,
    double_pads_default,
    get_cases,
)
from scdevice_pcells.simulations.double_pads_sqnl_eigenmode import target_metadata
from scdevice_pcells.simulations.epr.double_pads_sqnl import correction_cuts, partition_regions
from scdevice_pcells.simulations.export_paths import (
    create_or_empty_scdevice_tmp_directory,
    make_simulation_bat_location_independent,
)
from scdevice_pcells.simulations.transmon_targets import (
    C_SIGMA_TARGET_FF,
    F_GE_TARGET_GHZ,
    JUNCTION_INDUCTANCE_H,
    TARGET_SOURCE,
)


CASE_CSV = "epr_cases.csv"

EPR_SETTINGS = {
    "n_modes": 1,
    "min_frequency": 0.5,
    "max_delta_f": 0.008,
    "mesh_gap": 25,
    "maximum_passes": 17,
    "minimum_passes": 1,
    "minimum_converged_passes": 2,
}

SURFACE_LOSS_TANGENTS = {
    "MA": 9.9e-3,
    "MS": 2.6e-3,
    "SA": 2.1e-3,
    "substrate": 5e-7,
}


def epr_solution() -> AnsysEigenmodeSolution:
    return AnsysEigenmodeSolution(
        min_frequency=EPR_SETTINGS["min_frequency"],
        max_delta_f=EPR_SETTINGS["max_delta_f"],
        n_modes=EPR_SETTINGS["n_modes"],
        mesh_size={"1t1_gap": EPR_SETTINGS["mesh_gap"]},
        maximum_passes=EPR_SETTINGS["maximum_passes"],
        minimum_passes=EPR_SETTINGS["minimum_passes"],
        minimum_converged_passes=EPR_SETTINGS["minimum_converged_passes"],
        integrate_energies=True,
        simulation_flags=[],
    )


def correction_post_process(post_process):
    return post_process + [PostProcess("produce_q_factor_table.py", **SURFACE_LOSS_TANGENTS)]


def simulation_parameters(case, args, index):
    name = case_name(case, f"dpsqe{args.sweep[0]}{index:03d}_epr")
    geometry = {key: float(value) for key, value in case.items()}
    return {
        "name": name,
        "box": pya.DBox(pya.DPoint(0, 0), pya.DPoint(3000, 3000)),
        "face_stack": ["1t1"],
        "use_internal_ports": True,
        "use_ports": True,
        "waveguide_length": 200,
        "junction_inductance": JUNCTION_INDUCTANCE_H,
        "junction_capacitance": args.junction_capacitance_ff * 1e-15,
        "ground_gap": [case["ground_gap_width_um"], case["ground_gap_height_um"]],
        "a": float(double_pads_default("a")),
        "b": float(double_pads_default("b")),
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
        "tls_layer_thickness": 5e-3,
        "tls_sheet_approximation": True,
        "detach_tls_sheets_from_body": True,
        "metal_height": 0.2,
        "extra_json_data": {
            "epr_geometry": geometry,
            "epr_workflow": "ansys_eigenmode_ansys_mer_correction",
            **target_metadata(args.junction_capacitance_ff),
        },
    }


def make_simulations(layout, args):
    sim_class = get_single_element_sim_class(
        DoublePadsSQNL,
        sim_junction_type=SQNL_DIRECT_LEAD_SIM,
        partition_region_function=partition_regions,
    )
    solution = epr_solution()
    simulations = [
        (sim_class(layout, **simulation_parameters(case, args, index)), solution)
        for index, case in enumerate(get_cases(args))
    ]
    logging.info("Prepared %d DoublePadsSQNL MER-corrected EPR simulation case(s).", len(simulations))
    return simulations


def simulation_objects(simulations):
    return [simulation for simulation, _ in simulations]


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
    for simulation in simulation_objects(simulations):
        metadata = simulation.extra_json_data
        geometry = metadata["epr_geometry"]
        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        rows.append(
            {
                "name": simulation.name,
                "workflow": metadata["epr_workflow"],
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


def prepare_export_path(args):
    if args.export_dir:
        args.export_dir.mkdir(parents=True, exist_ok=True)
        return args.export_dir
    return create_or_empty_scdevice_tmp_directory(f"{Path(__file__).stem}_{args.sweep}")


def export_workflow(simulations, export_path):
    simulation_oas = export_simulation_oas(simulations, export_path)
    write_case_metadata(simulations, export_path)
    export_ansys(
        simulations,
        path=export_path,
        file_prefix="simulation",
        exit_after_run=True,
        post_process=PostProcess("epr", command=None, folder=""),
    )

    correction_simulations, post_process = get_epr_correction_simulations(
        simulations,
        correction_cuts,
        metal_height=0.2,
    )
    correction_oas = export_simulation_oas(correction_simulations, export_path, "epr")
    export_ansys(
        correction_simulations,
        path=export_path,
        file_prefix="epr",
        exit_after_run=True,
        post_process=correction_post_process(post_process),
    )

    make_simulation_bat_location_independent(export_path, "simulation")
    make_simulation_bat_location_independent(export_path, "epr")
    return simulation_oas, correction_oas, correction_simulations


def load_exported_json(export_path, simulation, solution=None):
    solution_name = "" if solution is None else solution.name
    with open(export_path / f"{simulation.name}{solution_name}.json", "r", encoding="utf-8-sig") as file:
        return json.load(file)


def first_value(value):
    return value[0] if isinstance(value, list) else value


def layer_excitations(exported):
    return {
        layer_data["excitation"]
        for layer_data in exported["layers"].values()
        if isinstance(layer_data, dict) and "excitation" in layer_data
    }


def run_smoke_check(simulations, correction_simulations, export_path):
    assert simulations, "No simulations were created."
    assert correction_simulations, "No correction simulations were created."
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas."
    assert (export_path / "epr.oas").exists(), "Missing epr.oas."
    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat."
    assert (export_path / "epr.bat").exists(), "Missing epr.bat."
    assert (export_path / CASE_CSV).exists(), f"Missing {CASE_CSV}."

    expected_partition_names = {
        "junctiongapmer",
        "junctiontipmer",
        "tapermer",
        "couplerfeedmer",
        "couplerpaddlemer",
        "islandpadmer",
        "islandpadbulk",
        "1t1complementmer",
        "1t1complementbulk",
    }

    for simulation, solution in simulations:
        exported = load_exported_json(export_path, simulation, solution)
        parameters = exported["parameters"]
        analysis_setup = exported["analysis_setup"]
        flags = exported.get("simulation_flags") or parameters.get("simulation_flags")
        flags = [] if flags is None else flags

        assert exported["ansys_tool"] == "eigenmode"
        assert exported["integrate_energies"] is True
        assert flags == []
        assert analysis_setup["n_modes"] == EPR_SETTINGS["n_modes"]
        assert analysis_setup["min_frequency"] == EPR_SETTINGS["min_frequency"]
        assert analysis_setup["max_delta_f"] == EPR_SETTINGS["max_delta_f"]
        assert exported["mesh_size"] == {"1t1_gap": EPR_SETTINGS["mesh_gap"]}

        assert parameters["tls_sheet_approximation"] is True
        assert parameters["detach_tls_sheets_from_body"] is True
        assert abs(first_value(parameters["tls_layer_thickness"]) - 5e-3) < 1e-12
        assert abs(first_value(parameters["metal_height"]) - 0.2) < 1e-12

        metadata = parameters["extra_json_data"]
        assert metadata["epr_workflow"] == "ansys_eigenmode_ansys_mer_correction"
        assert metadata["target_source"] == TARGET_SOURCE
        assert metadata["target_C_sigma_fF"] == C_SIGMA_TARGET_FF
        assert metadata["junction_terminal_model"] == JUNCTION_TERMINAL_MODEL
        assert metadata["surrogate_pads_enabled"] is SURROGATE_PADS_ENABLED

        partition_names = {partition.name for partition in simulation.get_partition_regions()}
        assert expected_partition_names.issubset(partition_names)

        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        assert abs((upper.y - lower.y) - DIRECT_LEAD_ATTACH_SPAN_UM) < 1e-3
        assert_direct_taper_junction_port(simulation)

    for correction_simulation, solution in correction_simulations:
        exported = load_exported_json(export_path, correction_simulation, solution)
        assert exported["ansys_tool"] == "cross-section"
        assert exported["integrate_energies"] is True
        assert exported["mesh_size"].get("ma_layer_mer") == 0.0005
        assert exported["mesh_size"].get("ms_layer_mer") == 0.0005
        assert exported["mesh_size"].get("sa_layer_mer") == 0.0005
        assert any(layer_name.endswith("_mer") for layer_name in exported["layers"])
        excitations = layer_excitations(exported)
        assert 0 in excitations, f"Missing reference ground in {correction_simulation.name}."
        assert any(excitation > 0 for excitation in excitations if excitation is not None), (
            f"Missing signal conductor in {correction_simulation.name}."
        )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", choices=["single", "coarse", "refine"], default="single")
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

    export_path = prepare_export_path(args)
    layout = pya.Layout()
    simulations = make_simulations(layout, args)
    simulation_oas, correction_oas, correction_simulations = export_workflow(simulations, export_path)

    if args.smoke_check:
        run_smoke_check(simulations, correction_simulations, export_path)

    if args.open_oas:
        open_with_klayout_or_default_application(simulation_oas)
        open_with_klayout_or_default_application(correction_oas)


if __name__ == "__main__":
    main()
