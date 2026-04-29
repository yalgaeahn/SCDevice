"""HFSS export for an SQNL readout resonator crop generated from the full chip PCell."""

import argparse
import csv
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np

from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.port import EdgePort

from scdevice_pcells.simulations.ansys_batch import SIMULATION_BATCH_FILENAME, configure_ansys_batch
from scdevice_pcells.simulations.export_paths import create_or_empty_scdevice_tmp_directory
from scdevice_pcells.simulations.sqnl_readout_resonator_common import (
    DEFAULT_FEEDLINE_Y,
    add_feedline_edge_ports,
    build_sqnl_cell,
    crop_box_for_resonator,
    format_value,
    get_cell_refpoints,
    make_readout_metadata,
    make_simulation_from_cell,
    point_inside_box,
    readout_short_has_no_open_gap_cap,
)


def parse_lengths(value):
    if ":" not in value:
        return [float(part.strip()) for part in value.split(",") if part.strip()]
    start, stop, step = [float(part.strip()) for part in value.split(":")]
    if step <= 0:
        raise ValueError("Length sweep step must be positive.")
    return [start + i * step for i in range(int(math.floor((stop - start) / step + 1e-12)) + 1)]


def make_simulations(layout, args):
    simulations = []
    for length in parse_lengths(args.lengths):
        name = (
            f"sqnl_ro_qb{args.resonator_index}_len_{format_value(length)}"
            f"_cpl_{format_value(args.coupling_length)}_gap_{format_value(args.gap)}"
        )
        cell, selected_length, readout_res_lengths, readout_coupling_lengths = build_sqnl_cell(layout, args, length)
        refpoints = get_cell_refpoints(cell)
        crop_box = crop_box_for_resonator(refpoints, args)
        metadata = make_readout_metadata(args, selected_length, readout_res_lengths, readout_coupling_lengths, crop_box)
        simulation = make_simulation_from_cell(
            cell,
            refpoints,
            crop_box,
            args.resonator_index,
            name,
            metadata,
            use_ports=True,
            port_size=args.port_size,
        )
        add_feedline_edge_ports(simulation, crop_box)
        simulations.append(simulation)
    logging.info("Exporting %d HFSS case(s).", len(simulations))
    return simulations


def simulation_name_from_snp(path):
    return path.stem.replace("_project_SMatrix", "").replace("_SMatrix", "")


def load_parameters(export_path, simulation_name):
    json_path = export_path / f"{simulation_name}.json"
    if not json_path.exists():
        return {}
    with open(json_path, "r", encoding="utf-8-sig") as file:
        return json.load(file).get("parameters", {})


def metadata_from_parameters(parameters):
    metadata = parameters.get("extra_json_data") or {}
    return metadata if isinstance(metadata, dict) else {}


def crossing_frequency(frequency, power, index, target, direction):
    stop = 0 if direction < 0 else len(power) - 1
    i = index
    while i != stop:
        j = i + direction
        if (power[i] <= target <= power[j]) or (power[j] <= target <= power[i]):
            if abs(power[j] - power[i]) < 1e-30:
                return float(frequency[i])
            return float(frequency[i] + (target - power[i]) / (power[j] - power[i]) * (frequency[j] - frequency[i]))
        i = j
    return None


def estimate_notch_metrics(frequency_ghz, s21, qc_min, qc_max):
    power = np.abs(s21) ** 2
    index = int(np.argmin(power))
    edge_count = max(2, len(power) // 10)
    baseline = max(
        float(np.median(np.concatenate([power[:edge_count], power[-edge_count:]]))),
        float(np.max(power)),
    )

    target = power[index] + 0.5 * (baseline - power[index])
    left = crossing_frequency(frequency_ghz, power, index, target, -1)
    right = crossing_frequency(frequency_ghz, power, index, target, 1)
    bandwidth = None if left is None or right is None else right - left
    ql = None if bandwidth is None or bandwidth <= 0 else float(frequency_ghz[index] / bandwidth)

    s21_min = math.sqrt(max(float(power[index] / baseline), 0.0))
    qc = None if ql is None or s21_min >= 1 else float(ql / max(1e-12, 1 - s21_min))
    return {
        "f0_ghz": float(frequency_ghz[index]),
        "ql": ql,
        "qc_estimate": qc,
        "qc_in_target": bool(qc is not None and qc_min <= qc <= qc_max),
        "notch_depth_db": float(10 * math.log10(max(power[index] / baseline, 1e-300))),
    }


def summarize_results(export_path, qc_min, qc_max):
    import skrf as rf  # pylint: disable=import-outside-toplevel

    export_path = Path(export_path)
    rows = []
    for snp_path in sorted(export_path.glob("*_SMatrix.s*p")):
        sim_name = simulation_name_from_snp(snp_path)
        metadata = metadata_from_parameters(load_parameters(export_path, sim_name))
        network = rf.Network(str(snp_path))
        rows.append(
            {
                "simulation_name": sim_name,
                "resonator_index": metadata.get("resonator_index"),
                "resonator_length": metadata.get("resonator_length"),
                "coupling_length": metadata.get("coupling_length"),
                "feedline_resonator_gap": metadata.get("feedline_resonator_gap"),
                **estimate_notch_metrics(network.f / 1e9, network.s[:, 1, 0], qc_min, qc_max),
            }
        )

    if not rows:
        raise FileNotFoundError(f"No *_SMatrix.sNp files found in {export_path}")

    fieldnames = [
        "simulation_name",
        "resonator_index",
        "resonator_length",
        "coupling_length",
        "feedline_resonator_gap",
        "f0_ghz",
        "ql",
        "qc_estimate",
        "qc_in_target",
        "notch_depth_db",
    ]
    with open(export_path / "readout_resonator_summary.csv", "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with open(export_path / "readout_resonator_summary.json", "w", encoding="utf-8") as file:
        json.dump(rows, file, indent=4)


def run_smoke_check(simulations, export_path):
    for simulation in simulations:
        edge_ports = [port for port in simulation.ports if isinstance(port, EdgePort)]
        assert len(edge_ports) == 2
        assert abs(edge_ports[0].signal_location.x - simulation.box.left) < 1e-9
        assert abs(edge_ports[1].signal_location.x - simulation.box.right) < 1e-9
        assert edge_ports[0].signal_location.y == edge_ports[1].signal_location.y == DEFAULT_FEEDLINE_Y

        metadata = simulation.extra_json_data
        index = metadata["resonator_index"]
        assert metadata["readout_res_lengths"][index] == metadata["resonator_length"]
        assert metadata["readout_coupling_lengths"][index] == metadata["coupling_length"]
        assert metadata["readout_short_type"] == "galvanic_term1_0"
        assert point_inside_box(simulation.refpoints[f"qb_{index}_port_cplr"], simulation.box)
        assert point_inside_box(simulation.refpoints[f"qb_{index}_base"], simulation.box)
        assert point_inside_box(simulation.refpoints[f"readout_{index}_short"], simulation.box)
        assert readout_short_has_no_open_gap_cap(
            simulation,
            index,
            metadata.get("center_trace_width", 10),
            metadata.get("gap_width", 6),
        )

    assert (export_path / "simulation.oas").exists()
    assert (export_path / "simulation.bat").exists()
    assert (export_path / SIMULATION_BATCH_FILENAME).exists()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lengths", default="5200")
    parser.add_argument("--resonator-index", type=int, choices=range(6), default=0)
    parser.add_argument("--coupling-length", type=float, default=400)
    parser.add_argument("--gap", type=float, default=27)
    parser.add_argument("--turn-radius", type=float, default=50)
    parser.add_argument("--meander-width", type=float, default=350)
    parser.add_argument("--crop-half-width", type=float, default=1000)
    parser.add_argument("--crop-feedline-margin", type=float, default=500)
    parser.add_argument("--crop-qubit-margin", type=float, default=800)
    parser.add_argument("--center-trace-width", type=float, default=10)
    parser.add_argument("--gap-width", type=float, default=6)
    parser.add_argument("--port-size", type=float, default=200)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--summarize-only", action="store_true")
    parser.add_argument("--smoke-check", action="store_true")
    parser.add_argument("--qc-min", type=float, default=50000)
    parser.add_argument("--qc-max", type=float, default=100000)
    parser.add_argument("--frequency", type=float, default=5.0)
    parser.add_argument("--sweep-start", type=float, default=4.0)
    parser.add_argument("--sweep-end", type=float, default=8.0)
    parser.add_argument("--sweep-count", type=int, default=201)
    parser.add_argument("--max-delta-s", type=float, default=0.001)
    parser.add_argument("--maximum-passes", type=int, default=20)
    return parser.parse_known_args()[0]


def main():
    args = parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    export_path = args.export_dir or create_or_empty_scdevice_tmp_directory(Path(__file__).stem + "_hfss")
    export_path.mkdir(parents=True, exist_ok=True)

    if args.summarize_only:
        summarize_results(export_path, args.qc_min, args.qc_max)
        return

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
        maximum_passes=args.maximum_passes,
    )
    configure_ansys_batch(export_path, simulations, "hfss")

    if args.smoke_check:
        run_smoke_check(simulations, export_path)


if __name__ == "__main__":
    main()
