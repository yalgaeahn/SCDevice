"""HFSS pilot export for one SQNL feedline/readout resonator unit cell."""

import argparse
import csv
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np

from kqcircuits.elements.meander import Meander
from kqcircuits.elements.waveguide_coplanar import WaveguideCoplanar
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.export.ansys.ansys_export import export_ansys
from kqcircuits.simulations.export.simulation_export import export_simulation_oas
from kqcircuits.simulations.port import EdgePort
from kqcircuits.simulations.simulation import Simulation
from kqcircuits.util.parameters import Param, pdt

from scdevice_pcells.simulations.ansys_batch import SIMULATION_BATCH_FILENAME, configure_ansys_batch
from scdevice_pcells.simulations.export_paths import create_or_empty_scdevice_tmp_directory


def _num_meanders(meander_length, turn_radius, meander_width):
    return max(1, int((meander_length - turn_radius * (math.pi - 2)) / (meander_width + turn_radius * (math.pi - 2))))


class SqnlReadoutResonatorSim(Simulation):
    """Two-port CPW feedline coupled to one open-ended readout resonator."""

    resonator_length = Param(pdt.TypeDouble, "Total resonator centerline length", 5200, unit="um")
    coupling_length = Param(pdt.TypeDouble, "Feedline-parallel coupling length", 400, unit="um")
    feedline_resonator_gap = Param(pdt.TypeDouble, "Feedline-to-resonator centerline gap", 27, unit="um")
    resonator_turn_radius = Param(pdt.TypeDouble, "Resonator turn radius", 50, unit="um")
    resonator_meander_width = Param(pdt.TypeDouble, "Minimum resonator meander width", 350, unit="um")
    resonator_stem_length = Param(pdt.TypeDouble, "Open-end stem length", 500, unit="um")
    feedline_length = Param(pdt.TypeDouble, "Minimum feedline length", 3000, unit="um")
    feedline_port_padding = Param(pdt.TypeDouble, "Feedline padding outside resonator extents", 1000, unit="um")
    box_y_margin = Param(pdt.TypeDouble, "Vertical simulation box margin", 500, unit="um")

    def build(self):
        resonator_points, meander_start, num_meanders = self._produce_readout_resonator()
        meander_end = meander_start + pya.DPoint(0, 2 * self.resonator_turn_radius * (num_meanders + 1))

        x_values = [point.x for point in resonator_points + [meander_start, meander_end]]
        half_feedline = max(
            float(self.feedline_length) / 2,
            abs(min(x_values)) + float(self.feedline_port_padding),
            abs(max(x_values)) + float(self.feedline_port_padding),
        )
        feedline_start = pya.DPoint(-half_feedline, 0)
        feedline_end = pya.DPoint(half_feedline, 0)
        self.insert_cell(WaveguideCoplanar, path=pya.DPath([feedline_start, feedline_end], 1))

        y_values = [point.y for point in resonator_points + [meander_start, meander_end, feedline_start, feedline_end]]
        self.box = pya.DBox(feedline_start, feedline_end)
        self.box.bottom = min(y_values) - float(self.box_y_margin)
        self.box.top = max(y_values) + float(self.box_y_margin)
        self.ground_grid_box = self.box

        self.ports.append(EdgePort(1, feedline_start))
        self.ports.append(EdgePort(2, feedline_end))
        self.refpoints["feedline_port_1"] = feedline_start
        self.refpoints["feedline_port_2"] = feedline_end
        self.refpoints["resonator_open"] = resonator_points[0]
        self.refpoints["resonator_meander_start"] = meander_start
        self.refpoints["resonator_meander_end"] = meander_end

    def _produce_readout_resonator(self):
        turn_radius = float(self.resonator_turn_radius)
        coupling_length = float(self.coupling_length)
        coupling_y = float(self.feedline_resonator_gap)
        pos_start = pya.DPoint(coupling_length / 2, coupling_y + float(self.resonator_stem_length))
        meander_start_x = pos_start.x - coupling_length - 2 * turn_radius
        meander_start = pya.DPoint(meander_start_x, coupling_y + 2 * turn_radius)
        resonator_points = [
            pos_start,
            pya.DPoint(pos_start.x, coupling_y),
            pya.DPoint(meander_start_x, coupling_y),
            meander_start,
        ]

        non_meander = self.add_element(WaveguideCoplanar, path=pya.DPath(resonator_points, 1), r=turn_radius)
        self.insert_cell(non_meander)
        meander_length = float(self.resonator_length) - non_meander.length()
        if meander_length <= 4 * turn_radius:
            raise ValueError(f"resonator_length={self.resonator_length} um is too short for this geometry.")

        num_meanders = _num_meanders(meander_length, turn_radius, float(self.resonator_meander_width))
        self.insert_cell(
            Meander,
            start_point=meander_start,
            end_point=meander_start + pya.DPoint(0, 2 * turn_radius * (num_meanders + 1)),
            length=meander_length,
            meanders=num_meanders,
            r=turn_radius,
        )
        return resonator_points, meander_start, num_meanders


def parse_lengths(value):
    if ":" not in value:
        return [float(part.strip()) for part in value.split(",") if part.strip()]
    start, stop, step = [float(part.strip()) for part in value.split(":")]
    if step <= 0:
        raise ValueError("Length sweep step must be positive.")
    return [start + i * step for i in range(int(math.floor((stop - start) / step + 1e-12)) + 1)]


def format_value(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}".replace(".", "p")


def make_simulations(layout, args):
    simulations = []
    for length in parse_lengths(args.lengths):
        name = f"sqnl_ro_len_{format_value(length)}_cpl_{format_value(args.coupling_length)}_gap_{format_value(args.gap)}"
        simulations.append(
            SqnlReadoutResonatorSim(
                layout,
                name=name,
                face_stack=["1t1"],
                use_ports=True,
                port_size=args.port_size,
                a=args.center_trace_width,
                b=args.gap_width,
                resonator_length=length,
                coupling_length=args.coupling_length,
                feedline_resonator_gap=args.gap,
                resonator_turn_radius=args.turn_radius,
                resonator_meander_width=args.meander_width,
            )
        )
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
        params = load_parameters(export_path, sim_name)
        network = rf.Network(str(snp_path))
        rows.append(
            {
                "simulation_name": sim_name,
                "resonator_length": params.get("resonator_length"),
                "coupling_length": params.get("coupling_length"),
                "feedline_resonator_gap": params.get("feedline_resonator_gap"),
                **estimate_notch_metrics(network.f / 1e9, network.s[:, 1, 0], qc_min, qc_max),
            }
        )

    if not rows:
        raise FileNotFoundError(f"No *_SMatrix.sNp files found in {export_path}")

    fieldnames = [
        "simulation_name",
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
        assert len([port for port in simulation.ports if isinstance(port, EdgePort)]) == 2
    assert (export_path / "simulation.oas").exists()
    assert (export_path / "simulation.bat").exists()
    assert (export_path / SIMULATION_BATCH_FILENAME).exists()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lengths", default="5200")
    parser.add_argument("--coupling-length", type=float, default=400)
    parser.add_argument("--gap", type=float, default=27)
    parser.add_argument("--turn-radius", type=float, default=50)
    parser.add_argument("--meander-width", type=float, default=350)
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
