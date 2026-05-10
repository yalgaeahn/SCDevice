"""Capacitance export workflow for a single DoublePadsSQNL qubit."""

import argparse
import csv
import logging
import sys
from itertools import product
from pathlib import Path

from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.elmer.elmer_export import export_elmer
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.post_process import PostProcess
from kqcircuits.simulations.single_element_simulation import (
    get_single_element_sim_class,
)
from kqcircuits.util.export_helper import open_with_klayout_or_default_application

from scdevice_pcells.junctions import SQNL_DIRECT_LEAD_SIM
from scdevice_pcells.junctions.direct_lead_sim import (
    DIRECT_LEAD_ATTACH_SPAN_UM,
    JUNCTION_TERMINAL_MODEL,
    SURROGATE_PADS_ENABLED,
)
from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL
from scdevice_pcells.simulations.export_paths import (
    SCDEVICE_TMP_PATH,
    add_kq_post_process_tool_metadata,
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

CASE_CSV = "capacitance_cases.csv"
TRANSMON_REPORT_CSV = "transmon_target_report.csv"
TRANSMON_REPORT_SCRIPT = "produce_transmon_target_report.py"


def format_value(value):
    return f"{float(value):g}".replace("-", "m").replace(".", "p")


def base_case():
    return {
        "width_um": 800.0,
        "height_um": 150.0,
        "island_island_gap_um": 40.0,
        "taper_width_um": 10.0,
        "taper_junction_width_um": 2.0,
        "coupler_width_um": 150.0,
        "coupler_height_um": 20.0,
        "coupler_offset_um": 100.0,
        "coupler_a_um": 5.0,
        "ground_gap_width_um": 900.0,
        "ground_gap_height_um": 900.0,
    }


def coarse_cases():
    cases = []
    for width, height, island_gap in product(
        [800.0, 1000.0, 1200.0, 1300.0],
        [80.0, 100.0, 120.0, 150.0],
        [60.0, 80.0, 100.0, 120.0, 150.0],
    ):
        case = base_case()
        case.update(
            {
                "width_um": width,
                "height_um": height,
                "island_island_gap_um": island_gap,
            }
        )
        cases.append(case)
    return cases


def default_refine_source():
    return (
        SCDEVICE_TMP_PATH
        / "double_pads_sqnl_capacitance_elmer_coarse"
        / TRANSMON_REPORT_CSV
    )


def refine_cases(refine_source):
    source = Path(refine_source) if refine_source else default_refine_source()
    if not source.exists():
        raise FileNotFoundError(
            f"Refine sweep needs a secondary transmon target report at {source}. "
            "Run a coarse sweep, generate a separate target report from KQ standard results, "
            "or pass --refine-source."
        )

    cases = []
    seen = set()
    with open(source, "r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            try:
                if abs(float(row["target_error_fF"])) > 8.0:
                    continue
                width0 = float(row["width_um"])
                height0 = float(row["height_um"])
                gap0 = float(row["island_island_gap_um"])
            except (KeyError, TypeError, ValueError):
                continue

            for width in [width0 - 100.0, width0, width0 + 100.0]:
                for height in [height0 - 20.0, height0, height0 + 20.0]:
                    for island_gap in [gap0 - 20.0, gap0, gap0 + 20.0]:
                        for taper_width in [8.0, 10.0, 12.0, 16.0]:
                            for taper_junction_width in [2.0, 3.0, 4.0]:
                                for coupler_offset in [20.0, 40.0, 60.0]:
                                    if width <= 0 or height <= 0 or island_gap <= 0:
                                        continue
                                    key = (
                                        width,
                                        height,
                                        island_gap,
                                        taper_width,
                                        taper_junction_width,
                                        coupler_offset,
                                    )
                                    if key in seen:
                                        continue
                                    seen.add(key)
                                    case = base_case()
                                    case.update(
                                        {
                                            "width_um": width,
                                            "height_um": height,
                                            "island_island_gap_um": island_gap,
                                            "taper_width_um": taper_width,
                                            "taper_junction_width_um": (
                                                taper_junction_width
                                            ),
                                            "coupler_offset_um": coupler_offset,
                                        }
                                    )
                                    cases.append(case)

    if not cases:
        raise ValueError(
            f"No refine centers found within |C_sigma - {C_SIGMA_TARGET_FF} fF| <= 8 fF."
        )
    return cases


def get_cases(args):
    if args.sweep == "single":
        return [base_case()]
    if args.sweep == "coarse":
        return coarse_cases()
    return refine_cases(args.refine_source)


def case_name(case, prefix):
    return (
        f"{prefix}_w{format_value(case['width_um'])}"
        f"_h{format_value(case['height_um'])}"
        f"_g{format_value(case['island_island_gap_um'])}"
        f"_t{format_value(case['taper_width_um'])}"
        f"_j{format_value(case['taper_junction_width_um'])}"
        f"_o{format_value(case['coupler_offset_um'])}"
    )


def simulation_parameters(case, args, index):
    name = case_name(case, f"dps{args.sweep[0]}{index:03d}")
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
            "capacitance_geometry": geometry,
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
            "junction_capacitance_fF": args.junction_capacitance_ff,
            "sim_junction_type": SQNL_DIRECT_LEAD_SIM,
            "direct_lead_attach_span_um": DIRECT_LEAD_ATTACH_SPAN_UM,
            "junction_terminal_model": JUNCTION_TERMINAL_MODEL,
            "surrogate_pads_enabled": SURROGATE_PADS_ENABLED,
            "surrogate_pad_width_um": 0.0,
            "surrogate_pad_length_um": 0.0,
        },
    }


def make_simulations(layout, args):
    sim_class = get_single_element_sim_class(
        DoublePadsSQNL,
        sim_junction_type=SQNL_DIRECT_LEAD_SIM,
    )
    simulations = []
    for index, case in enumerate(get_cases(args)):
        simulations.append(
            sim_class(layout, **simulation_parameters(case, args, index))
        )
    logging.info("Prepared %d capacitance simulation case(s).", len(simulations))
    return simulations


def write_case_metadata(simulations, export_path):
    rows = []
    for simulation in simulations:
        metadata = simulation.extra_json_data
        geometry = metadata["capacitance_geometry"]
        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        rows.append(
            {
                "name": simulation.name,
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


def write_rows_csv(path, rows):
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def capacitance_post_processes():
    scdevice_post_process_path = Path(__file__).resolve().with_name("post_process")
    return [
        PostProcess("produce_cmatrix_table.py"),
        PostProcess(TRANSMON_REPORT_SCRIPT, folder=str(scdevice_post_process_path)),
    ]


def transmon_report_script_path():
    return Path(__file__).resolve().with_name("post_process") / TRANSMON_REPORT_SCRIPT


def prepare_export_path(args):
    if args.export_dir:
        path = args.export_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    dirname = f"{Path(__file__).stem}_{args.backend}_{args.sweep}"
    return create_or_empty_scdevice_tmp_directory(dirname)


def export_backend(simulations, export_path, args):
    oas = export_simulation_oas(simulations, export_path)
    write_case_metadata(simulations, export_path)

    if args.backend == "elmer":
        export_elmer(
            simulations,
            export_path,
            tool="capacitance",
            post_process=capacitance_post_processes(),
            workflow={
                "python_executable": "python",
                "n_workers": 4,
                "elmer_n_processes": -1,
                "gmsh_n_threads": -1,
                "elmer_n_threads": 1,
            },
            mesh_size={
                "global_max": 60.0,
                "1t1_gap&1t1_signal_1": [2.0, 4.0],
                "1t1_gap&1t1_signal_2": [2.0, 4.0],
                "1t1_gap&1t1_signal_3": [2.0, 4.0],
                "1t1_gap&1t1_ground": [2.0, 4.0],
            },
        )
    else:
        export_ansys(
            simulations,
            ansys_tool="q3d",
            path=export_path,
            exit_after_run=True,
            post_process=capacitance_post_processes(),
            percent_error=0.2,
            maximum_passes=10,
            minimum_passes=2,
            minimum_converged_passes=2,
        )
        add_kq_post_process_tool_metadata(export_path)
        make_simulation_bat_location_independent(export_path)
    return oas


def assert_point_close(actual, expected, label):
    assert actual.distance(expected) < 1e-6, (
        f"{label} mismatch: got ({actual.x}, {actual.y}), "
        f"expected ({expected.x}, {expected.y})."
    )


def assert_direct_taper_junction_port(simulation):
    upper = simulation.refpoints["junction_attach_island_1"]
    lower = simulation.refpoints["junction_attach_island_2"]
    assert_point_close(simulation.refpoints["port_squid_a"], upper, "port_squid_a")
    assert_point_close(simulation.refpoints["port_squid_b"], lower, "port_squid_b")

    junction_ports = [
        port for port in simulation.ports if getattr(port, "junction", False)
    ]
    assert junction_ports, "Missing junction internal port."
    for port in junction_ports:
        assert abs(port.inductance - JUNCTION_INDUCTANCE_H) < 1e-15
        assert hasattr(port, "ground_location"), "Junction port must have two ends."
        assert abs(port.signal_location.x - upper.x) < 1e-6
        assert abs(port.ground_location.x - lower.x) < 1e-6
        assert abs(port.signal_location.y - (upper.y + simulation.over_etching)) < 1e-6
        assert abs(port.ground_location.y - (lower.y - simulation.over_etching)) < 1e-6


def run_smoke_check(simulations, export_path, backend):
    assert simulations, "No simulations were created."
    assert (export_path / "simulation.oas").exists()
    assert (export_path / CASE_CSV).exists()

    if backend == "elmer":
        assert list(
            export_path.glob("*.json")
        ), "Elmer export did not write JSON files."
        assert (
            export_path / "scripts" / "run.py"
        ).exists(), "Elmer export did not write scripts/run.py."
        assert transmon_report_script_path().exists()
    else:
        bat_path = export_path / "simulation.bat"
        assert bat_path.exists()
        bat_text = bat_path.read_text(encoding="utf-8")
        assert "produce_cmatrix_table.py" in bat_text
        assert TRANSMON_REPORT_SCRIPT in bat_text
        assert str(transmon_report_script_path()) in bat_text

    for simulation in simulations:
        upper = simulation.refpoints["junction_attach_island_1"]
        lower = simulation.refpoints["junction_attach_island_2"]
        center = simulation.box.center()
        midpoint_y = (upper.y + lower.y) / 2
        assert abs(upper.x - center.x) < 1e-6
        assert abs(lower.x - center.x) < 1e-6
        assert abs(midpoint_y - (center.y + simulation.squid_offset)) < 1e-6
        assert abs((upper.y - lower.y) - DIRECT_LEAD_ATTACH_SPAN_UM) < 1e-3
        assert simulation.extra_json_data["junction_terminal_model"] == (
            JUNCTION_TERMINAL_MODEL
        )
        assert simulation.extra_json_data["surrogate_pads_enabled"] is False
        assert simulation.extra_json_data["surrogate_pad_width_um"] == 0.0
        assert simulation.extra_json_data["surrogate_pad_length_um"] == 0.0
        assert_direct_taper_junction_port(simulation)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sweep", choices=["single", "coarse", "refine"], default="single"
    )
    parser.add_argument("--backend", choices=["elmer", "q3d"], default="q3d")
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
        "Target from %s: fge=%.5f GHz, fef=%.5f GHz, alpha=%.3f GHz, C_sigma=%.4f fF, LJ=%.5f nH.",
        TARGET_SOURCE,
        F_GE_TARGET_GHZ,
        F_EF_TARGET_GHZ,
        ANHARMONICITY_TARGET_GHZ,
        C_SIGMA_TARGET_FF,
        JUNCTION_INDUCTANCE_H / 1e-9,
    )

    export_path = prepare_export_path(args)
    export_path.mkdir(parents=True, exist_ok=True)

    layout = pya.Layout()
    simulations = make_simulations(layout, args)
    oas = export_backend(simulations, export_path, args)

    if args.smoke_check:
        run_smoke_check(simulations, export_path, args.backend)
    if args.open_oas:
        open_with_klayout_or_default_application(oas)


if __name__ == "__main__":
    main()
