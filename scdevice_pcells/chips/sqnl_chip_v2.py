"""SQNL single-qubit chip v2 with readout coupling before the meander."""

from kqcircuits.elements.meander import Meander
from kqcircuits.pya_resolver import pya

from scdevice_pcells.chips.sqnl_chip_v1 import SqnlSingle, _get_num_meanders
from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL


V1_QUBIT_SPACING_Y = 2600
V2_QUBIT_SPACING_Y = 3200


class SqnlSingleV2(SqnlSingle):
    """Single-qubit SQNL chip with qubit-side feedline coupling topology.

    The readout resonator starts at the qubit-side coupler, routes toward the
    feedline, follows the feedline for the coupling section, then meanders to a
    galvanically shorted endpoint.
    """

    def _produce_qubits(self):
        """Produces one lifted DoublePadsSQNL qubit in a predefined position."""
        qubit = self.add_element(
            DoublePadsSQNL,
            junction_type=self.junction_type,
            drive_position=[-450, 0],
        )
        qubits_center_x = 5e3 + 400
        y_a = float(self.feedline_y) + V2_QUBIT_SPACING_Y / 2
        qb0_refpoints = self._produce_qubit(qubit, qubits_center_x, y_a, 2, "qb_0")
        return (qb0_refpoints,)

    def _produce_readout_resonator(self, total_length, coupling_length, pos_cplr, above_feedline, resonator_index=None):
        """Produces a readout resonator coupled to a qubit and feedline."""
        factor = 1 if above_feedline else -1
        turn_radius = float(self.readout_turn_radius)
        distance_to_feedline = float(self.readout_feedline_gap)
        feedline_y = float(self.feedline_y)
        feedline_coupling_y = feedline_y + factor * distance_to_feedline

        coupling_end_x = pos_cplr.x - (coupling_length + 2 * turn_radius)
        meander_start = pya.DPoint(
            coupling_end_x,
            feedline_y + factor * distance_to_feedline + factor * 2 * turn_radius,
        )

        coupler_waveguide = self._produce_waveguide(
            [
                pos_cplr,
                pya.DPoint(pos_cplr.x, feedline_coupling_y),
                pya.DPoint(coupling_end_x, feedline_coupling_y),
                meander_start,
            ],
            turn_radius=turn_radius,
        )
        len_coupler = coupler_waveguide.length()
        meander_length = total_length - len_coupler
        if meander_length <= 2 * turn_radius:
            raise ValueError(
                "Readout resonator length is too short for the v2 feedline coupling section. "
                f"total_length={total_length}, non_meander_length={len_coupler}."
            )

        qubit_lift = (V2_QUBIT_SPACING_Y - V1_QUBIT_SPACING_Y) / 2
        short_end = pya.DPoint(coupling_end_x, pos_cplr.y - factor * qubit_lift)
        direct_meander_length = meander_start.distance(short_end)
        if meander_length <= direct_meander_length:
            raise ValueError(
                "Readout resonator remaining length must exceed the direct meander endpoint distance. "
                f"remaining_length={meander_length}, direct_distance={direct_meander_length}."
            )

        w = float(self.readout_meander_width)
        num_meanders = _get_num_meanders(meander_length, turn_radius, w)
        max_meanders = max(1, int(direct_meander_length / (2 * turn_radius) - 1))
        num_meanders = min(num_meanders, max_meanders)
        if num_meanders < 1:
            raise ValueError("Readout resonator v2 meander requires at least one meander.")

        self.insert_cell(
            Meander,
            start_point=meander_start,
            end_point=short_end,
            length=meander_length,
            meanders=num_meanders,
            r=turn_radius,
        )
        if resonator_index is not None:
            self.refpoints[f"readout_{resonator_index}_short"] = short_end
