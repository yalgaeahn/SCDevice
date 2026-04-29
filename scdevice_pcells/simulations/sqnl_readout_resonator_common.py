"""Shared helpers for SQNL readout resonator crop simulations."""

import contextlib
import logging

from kqcircuits.defaults import default_layers
from kqcircuits.elements.element import get_refpoints
from kqcircuits.pya_resolver import pya
from kqcircuits.simulations.empty_simulation import EmptySimulation
from kqcircuits.simulations.port import EdgePort

from scdevice_pcells.chips.sqnl_chip import SqnlSingle


DEFAULT_READOUT_RES_LENGTHS = [5000, 5100, 5200, 5300, 5400, 5500]
DEFAULT_READOUT_COUPLING_LENGTHS = [400] * 6
DEFAULT_FEEDLINE_Y = 5000


def format_value(value):
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:g}".replace(".", "p")


def get_cell_refpoints(cell):
    refpoint_layer = cell.layout().layer(default_layers["refpoints"])
    return get_refpoints(refpoint_layer, cell, rec_levels=None)


def point_inside_box(point, box):
    return box.left <= point.x <= box.right and box.bottom <= point.y <= box.top


def readout_short_has_no_open_gap_cap(
    simulation,
    resonator_index,
    center_trace_width,
    gap_width,
    probe_length=20,
):
    """Return True when no open-end cap gap exists beyond the readout short endpoint."""
    short = simulation.refpoints[f"readout_{resonator_index}_short"]
    half_width = center_trace_width / 2 + gap_width
    epsilon = 0.1

    if resonator_index < 3:
        probe_box = pya.DBox(
            pya.DPoint(short.x - half_width, short.y + epsilon),
            pya.DPoint(short.x + half_width, short.y + probe_length),
        )
    else:
        probe_box = pya.DBox(
            pya.DPoint(short.x - half_width, short.y - probe_length),
            pya.DPoint(short.x + half_width, short.y - epsilon),
        )

    gap_region = pya.Region(simulation.cell.begin_shapes_rec(simulation.get_layer("base_metal_gap_wo_grid")))
    probe_region = pya.Region(probe_box.to_itype(simulation.cell.layout().dbu))
    return (gap_region & probe_region).is_empty()


@contextlib.contextmanager
def suppress_from_cell_cell_warning():
    class FromCellCellWarningFilter(logging.Filter):
        def filter(self, record):
            return not record.getMessage().startswith("Trying to set parameters which do not exist: {'cell'} for ")

    warning_filter = FromCellCellWarningFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(warning_filter)
    try:
        yield
    finally:
        root_logger.removeFilter(warning_filter)


def selected_readout_parameters(resonator_index, resonator_length=None, coupling_length=400):
    readout_res_lengths = list(DEFAULT_READOUT_RES_LENGTHS)
    readout_coupling_lengths = list(DEFAULT_READOUT_COUPLING_LENGTHS)
    selected_length = readout_res_lengths[resonator_index] if resonator_length is None else resonator_length
    readout_res_lengths[resonator_index] = selected_length
    readout_coupling_lengths[resonator_index] = coupling_length
    return selected_length, readout_res_lengths, readout_coupling_lengths


def build_sqnl_cell(layout, args, resonator_length=None):
    selected_length, readout_res_lengths, readout_coupling_lengths = selected_readout_parameters(
        args.resonator_index,
        resonator_length,
        args.coupling_length,
    )

    cell = SqnlSingle.create(
        layout,
        name_chip="BASIC",
        with_grid=False,
        use_test_resonators=False,
        junction_type="Sim",
        name_mask="SQNL",
        name_copy=None,
        a=args.center_trace_width,
        b=args.gap_width,
        readout_res_lengths=readout_res_lengths,
        readout_coupling_lengths=readout_coupling_lengths,
        readout_feedline_gap=args.gap,
        readout_turn_radius=args.turn_radius,
        readout_meander_width=args.meander_width,
        feedline_y=DEFAULT_FEEDLINE_Y,
        feedline_x_distance=1200,
        use_readout_resonators=True,
        use_qubits=True,
    )
    return cell, selected_length, readout_res_lengths, readout_coupling_lengths


def crop_box_for_resonator(refpoints, args):
    index = args.resonator_index
    cplr = refpoints[f"qb_{index}_port_cplr"]
    base = refpoints[f"qb_{index}_base"]
    left = cplr.x - args.crop_half_width
    right = cplr.x + args.crop_half_width

    if left < refpoints["W_port"].x or right > refpoints["E_port"].x:
        raise ValueError("Crop x range must stay inside the straight W-E feedline segment.")

    if index < 3:
        bottom = DEFAULT_FEEDLINE_Y - args.crop_feedline_margin
        top = base.y + args.crop_qubit_margin
    else:
        bottom = base.y - args.crop_qubit_margin
        top = DEFAULT_FEEDLINE_Y + args.crop_feedline_margin
    return pya.DBox(pya.DPoint(left, bottom), pya.DPoint(right, top))


def make_readout_metadata(args, resonator_length, readout_res_lengths, readout_coupling_lengths, crop_box):
    return {
        "resonator_index": args.resonator_index,
        "resonator_length": resonator_length,
        "coupling_length": args.coupling_length,
        "feedline_resonator_gap": args.gap,
        "center_trace_width": args.center_trace_width,
        "gap_width": args.gap_width,
        "readout_res_lengths": readout_res_lengths,
        "readout_coupling_lengths": readout_coupling_lengths,
        "readout_short_type": "galvanic_term1_0",
        "crop_box": crop_box,
        "source_cell": "SqnlSingle",
    }


def make_simulation_from_cell(
    cell,
    refpoints,
    crop_box,
    resonator_index,
    name,
    metadata,
    use_ports=True,
    port_size=None,
    simulation_kwargs=None,
):
    kwargs = {
        "margin": 0,
        "box": crop_box,
        "ground_grid_box": crop_box,
        "name": name,
        "face_stack": ["1t1"],
        "use_ports": use_ports,
        "extra_json_data": metadata,
    }
    if port_size is not None:
        kwargs["port_size"] = port_size
    if simulation_kwargs is not None:
        kwargs.update(simulation_kwargs)

    with suppress_from_cell_cell_warning():
        simulation = EmptySimulation.from_cell(cell, **kwargs)

    for key in (
        "W_port",
        "E_port",
        f"qb_{resonator_index}_port_cplr",
        f"qb_{resonator_index}_base",
        f"readout_{resonator_index}_short",
    ):
        if key in refpoints:
            simulation.refpoints[key] = refpoints[key]
    return simulation


def add_feedline_edge_ports(simulation, crop_box):
    simulation.ports.append(EdgePort(1, pya.DPoint(crop_box.left, DEFAULT_FEEDLINE_Y)))
    simulation.ports.append(EdgePort(2, pya.DPoint(crop_box.right, DEFAULT_FEEDLINE_Y)))
    simulation.refpoints["crop_port_1"] = simulation.ports[0].signal_location
    simulation.refpoints["crop_port_2"] = simulation.ports[1].signal_location
