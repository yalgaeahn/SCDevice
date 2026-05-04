"""Eigenmode export for one SQNL readout resonator crop generated from the full chip PCell."""

import argparse
import json
import logging
import sys
from pathlib import Path

from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.post_process import PostProcess

from scdevice_pcells.simulations.export_paths import (
    create_or_empty_scdevice_tmp_directory,
    make_simulation_bat_location_independent,
)
from scdevice_pcells.simulations.sqnl_readout_resonator_common import (
    build_sqnl_cell,
    crop_box_for_resonator,
    format_value,
    get_cell_refpoints,
    make_readout_metadata,
    make_simulation_from_cell,
    point_inside_box,
    readout_short_has_no_open_gap_cap,
)

FAST_EIGENMODE_DEFAULTS = {
    "min_frequency": 3.5,
    "n_modes": 1,
    "max_delta_f": 0.05,
    "maximum_passes": 8,
    "minimum_passes": 1,
    "minimum_converged_passes": 1,
    "mesh_gap": 50,
}
PYEPR_EIGENMODE_DEFAULTS = {
    "min_frequency": 0.5,
    "n_modes": 4,
    "max_delta_f": 0.008,
    "maximum_passes": 17,
    "minimum_passes": 1,
    "minimum_converged_passes": 2,
    "mesh_gap": 25,
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


def apply_eigenmode_defaults(args):
    defaults = PYEPR_EIGENMODE_DEFAULTS if args.with_pyepr else FAST_EIGENMODE_DEFAULTS
    for name, value in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, value)
    return args


def make_simulation(layout, args):
    cell, selected_length, readout_res_lengths, readout_coupling_lengths = (
        build_sqnl_cell(layout, args, args.length)
    )
    refpoints = get_cell_refpoints(cell)
    crop_box = crop_box_for_resonator(refpoints, args)
    mode = "pyepr" if args.with_pyepr else "fast"
    name = (
        f"sqnl_ro_qb{args.resonator_index}_eigen_{mode}_len_{format_value(selected_length)}"
        f"_cpl_{format_value(args.coupling_length)}_gap_{format_value(args.gap)}"
    )
    metadata = make_readout_metadata(
        args, selected_length, readout_res_lengths, readout_coupling_lengths, crop_box
    )
    metadata["eigenmode_mode"] = mode
    simulation_kwargs = {}
    if args.with_pyepr:
        simulation_kwargs.update(
            {
                "tls_layer_thickness": 5e-3,
                "tls_sheet_approximation": True,
            }
        )
    return make_simulation_from_cell(
        cell,
        refpoints,
        crop_box,
        args.resonator_index,
        name,
        metadata,
        use_ports=False,
        simulation_kwargs=simulation_kwargs,
    )


def load_exported_json(export_path, simulation):
    with open(
        export_path / f"{simulation.name}.json", "r", encoding="utf-8-sig"
    ) as file:
        return json.load(file)


def run_smoke_check(simulation, export_path, args):
    assert (export_path / "simulation.oas").exists(), "Missing simulation.oas"
    assert (export_path / "simulation.bat").exists(), "Missing simulation.bat"
    simulation_bat = (export_path / "simulation.bat").read_text(encoding="utf-8")
    if args.with_pyepr:
        assert "run_pyepr_t1_estimate.py" in simulation_bat
    else:
        assert "run_pyepr_t1_estimate.py" not in simulation_bat

    exported = load_exported_json(export_path, simulation)
    assert exported["ports"] == [], "Eigenmode crop must not export feedline EdgePorts"

    parameters = exported["parameters"]
    assert parameters["n_modes"] == args.n_modes
    assert parameters["min_frequency"] == args.min_frequency
    assert parameters["max_delta_f"] == args.max_delta_f
    assert parameters["simulation_flags"] == (["pyepr"] if args.with_pyepr else [])
    assert parameters["mesh_size"] == {"1t1_gap": args.mesh_gap}

    metadata = simulation.extra_json_data
    index = metadata["resonator_index"]
    assert metadata["readout_res_lengths"][index] == metadata["resonator_length"]
    assert metadata["readout_coupling_lengths"][index] == metadata["coupling_length"]
    assert metadata["readout_short_type"] == "galvanic_term1_0"
    assert metadata["eigenmode_mode"] == ("pyepr" if args.with_pyepr else "fast")
    assert point_inside_box(
        simulation.refpoints[f"qb_{index}_port_cplr"], simulation.box
    )
    assert point_inside_box(simulation.refpoints[f"qb_{index}_base"], simulation.box)
    assert point_inside_box(
        simulation.refpoints[f"readout_{index}_short"], simulation.box
    )
    assert readout_short_has_no_open_gap_cap(
        simulation,
        index,
        metadata.get("center_trace_width", 10),
        metadata.get("gap_width", 6),
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resonator-index", type=int, choices=range(6), default=0)
    parser.add_argument("--length", type=float)
    parser.add_argument("--coupling-length", type=float, default=400)
    parser.add_argument("--gap", type=float, default=27)
    parser.add_argument("--turn-radius", type=float, default=50)
    parser.add_argument("--meander-width", type=float, default=350)
    parser.add_argument("--crop-half-width", type=float, default=1000)
    parser.add_argument("--crop-feedline-margin", type=float, default=500)
    parser.add_argument("--crop-qubit-margin", type=float, default=800)
    parser.add_argument("--center-trace-width", type=float, default=10)
    parser.add_argument("--gap-width", type=float, default=6)
    parser.add_argument(
        "--with-pyepr",
        action="store_true",
        help="Enable TLS layers, field saving, and pyEPR export",
    )
    parser.add_argument(
        "--pyepr", dest="with_pyepr", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--min-frequency", type=float)
    parser.add_argument("--n-modes", type=int)
    parser.add_argument("--max-delta-f", type=float)
    parser.add_argument("--maximum-passes", type=int)
    parser.add_argument("--minimum-passes", type=int)
    parser.add_argument("--minimum-converged-passes", type=int)
    parser.add_argument("--mesh-gap", type=float)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--smoke-check", action="store_true")
    return apply_eigenmode_defaults(parser.parse_known_args()[0])


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    export_path = args.export_dir or create_or_empty_scdevice_tmp_directory(
        Path(__file__).stem + "_eigenmode"
    )
    export_path.mkdir(parents=True, exist_ok=True)

    layout = pya.Layout()
    simulation = make_simulation(layout, args)
    export_simulation_oas([simulation], export_path)
    export_ansys(
        [simulation],
        ansys_tool="eigenmode",
        path=export_path,
        exit_after_run=False,
        min_frequency=args.min_frequency,
        max_delta_f=args.max_delta_f,
        n_modes=args.n_modes,
        mesh_size={"1t1_gap": args.mesh_gap},
        maximum_passes=args.maximum_passes,
        minimum_passes=args.minimum_passes,
        minimum_converged_passes=args.minimum_converged_passes,
        simulation_flags=["pyepr"] if args.with_pyepr else [],
        post_process=pyepr_post_process() if args.with_pyepr else None,
    )
    make_simulation_bat_location_independent(export_path)

    if args.smoke_check:
        run_smoke_check(simulation, export_path, args)


if __name__ == "__main__":
    main()
