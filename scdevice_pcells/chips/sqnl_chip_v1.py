# This code is part of KQCircuits
# Copyright (C) 2021 IQM Finland Oy
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not, see
# https://www.gnu.org/licenses/gpl-3.0.html.
#
# The software distribution should follow IQM trademark policy for open-source software
# (meetiqm.com/iqm-open-source-trademark-policy). IQM welcomes contributions to the code.
# Please see our contribution agreements for individuals (meetiqm.com/iqm-individual-contributor-license-agreement)
# and organizations (meetiqm.com/iqm-organization-contributor-license-agreement).


from math import pi

from kqcircuits.chips.chip import Chip
from kqcircuits.elements.meander import Meander

from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL

from kqcircuits.elements.waveguide_coplanar import WaveguideCoplanar
from kqcircuits.elements.waveguide_coplanar_splitter import WaveguideCoplanarSplitter, t_cross_parameters
from kqcircuits.pya_resolver import pya
from kqcircuits.util.coupler_lib import cap_params
from kqcircuits.util.parameters import Param, pdt, add_parameters_from
from kqcircuits.junctions.junction import Junction
from scdevice_pcells.junctions import SQNL_MANHATTAN_SINGLE_JUNCTION


def _get_num_meanders(meander_length, turn_radius, meander_min_width):
    """Get the required number of meanders to create a meander element with the given parameters."""

    return int((meander_length - turn_radius * (pi - 2)) / (meander_min_width + turn_radius * (pi - 2)))


@add_parameters_from(Junction, junction_type=SQNL_MANHATTAN_SINGLE_JUNCTION)
class SqnlSingle(Chip):
    """The PCell declaration for a single-qubit SQNL chip.

    The SQNL single chip has one qubit coupled by one readout resonator to a horizontal feedline.

    Attributes:
        launchers: A dictionary where the keys are names of the launchers and values are tuples whose first elements
            are positions of the launchers.

        qubits_refpoints: A tuple containing the refpoints for the single qubit.

    """

    readout_res_lengths = Param(
        pdt.TypeList, "Readout resonator lengths", [5000]
    )
    readout_coupling_lengths = Param(
        pdt.TypeList, "Readout resonator feedline coupling lengths", [400]
    )
    readout_feedline_gap = Param(
        pdt.TypeDouble,
        "Centerline distance between feedline and readout resonator coupling section",
        27,
        unit="um",
    )
    readout_turn_radius = Param(pdt.TypeDouble, "Readout resonator turn radius", 50, unit="um")
    readout_meander_width = Param(pdt.TypeDouble, "Minimum readout resonator meander width", 350, unit="um")
    feedline_y = Param(pdt.TypeDouble, "Feedline horizontal centerline y-coordinate", 5000, unit="um")
    feedline_x_distance = Param(
        pdt.TypeDouble,
        "Horizontal launcher escape distance before routing to the feedline",
        1200,
        unit="um",
    )
    
    use_readout_resonators = Param(pdt.TypeBoolean, "Place readout resonators", True)
    use_qubits = Param(pdt.TypeBoolean, "Place qubits", True)
    use_test_resonators = Param(pdt.TypeBoolean, "Use test resonators", False)
    test_res_lengths = Param(pdt.TypeList, "Test resonator lengths (four resonators)", [5200, 5400, 5600, 5800])
    n_fingers = Param(pdt.TypeList, "Number of fingers for test resonator couplers", [4, 4, 2, 4])
    l_fingers = Param(pdt.TypeList, "Length of fingers for test resonator couplers", [23.1, 9.9, 14.1, 10, 21])
    type_coupler = Param(
        pdt.TypeList,
        "Coupler type for test resonator couplers",
        ["interdigital", "interdigital", "interdigital", "gap"],
    )

    def build(self):
        """Produces a SingleXmons PCell."""
        self.name_mask = "M001"
        self.name_chip = "BASIC"
        self.name_copy = "KAIST"
        self.name_brand = "SQNL"

        # self.produce_junction_tests(self.junction_type)
        # self.launchers = self.produce_launchers("SMA8")
        self.launchers = self._produce_launchers()
        self.qubits_refpoints = ()

        if self.use_test_resonators:
            raise ValueError(
                "Test resonators require the old multi-qubit SQNL chip layout."
            )

        if self.use_qubits or self.use_readout_resonators or self.use_test_resonators:
            self.qubits_refpoints = self._produce_qubits()

        if self.use_readout_resonators:
            self._produce_readout_resonators()

        feedline_x_distance = float(self.feedline_x_distance)
        if self.use_test_resonators:
            self._produce_feedline_and_test_resonators(feedline_x_distance)
        else:
            self._produce_feedline(feedline_x_distance)

        # Charge lines still depend on the old eight-launcher layout, so they are disabled here.

    def _produce_launchers(self):
        return self.produce_n_launchers(
            n=(0, 1, 0, 1),
            launcher_type="RF",
            launcher_width=300,
            launcher_gap=260,
            launcher_indent=800,
            launcher_frame_gap=180,
            pad_pitch=5000,
            chip_box=pya.DBox(pya.DPoint(0, 0), pya.DPoint(10000, 10000)),
            launcher_assignments={
                1: "E",
                2: "W",
            }

        )

    def _produce_waveguide(self, path, term1=0, term2=0, turn_radius=None):
        """Produces a coplanar waveguide that follows the given path.

        Args:
            path: a DPath object determining the waveguide path
            term1: term1 of the waveguide
            term2: term2 of the waveguide
            turn_radius: turn_radius of the waveguide

        Returns:
            length of the produced waveguide

        """
        if turn_radius is None:
            turn_radius = self.r
        waveguide = self.add_element(
            WaveguideCoplanar,
            path=pya.DPath(path, 1),
            r=turn_radius,
            term1=term1,
            term2=term2,
        )
        self.insert_cell(waveguide)
        return waveguide

    def _produce_qubit(self, qubit_cell, center_x, center_y, rotation, name=None):
        """Produces a qubit in a SingleXmons chip.

        Args:
            qubit_cell: PCell of the qubit.
            center_x: X-coordinate of the center of the qubit.
            center_y: Y-coordinate of the center of the qubit.
            rotation: An integer which defines the rotation of the qubit in units of 90 degrees.
            name: A string containing the name of this qubit. Used to set the "id" property of the qubit instance.

        Returns:
            refpoints of the qubit.

        """
        qubit_trans = pya.DTrans(rotation, False, center_x, center_y)
        _, refpoints_abs = self.insert_cell(qubit_cell, qubit_trans, name, rec_levels=None)
        return refpoints_abs

    def _produce_qubits(self):
        """Produces one DoublePadsSQNL qubit in a predefined position.

        Returns:
            A tuple containing the refpoints of the single qubit.

        """
        # qubit = self.add_element(
        #     Swissmon,
        #     fluxline_type="none",
        #     arm_length=[146] * 4,
        #     arm_width=[24] * 4,
        #     gap_width=[24] * 4,
        #     island_r=2,
        #     cpl_length=[0, 140, 0],
        #     cpl_width=[60, 24, 60],
        #     cpl_gap=[110, 102, 110],
        #     cl_offset=[200, 200],
        # )
        qubit = self.add_element(
            DoublePadsSQNL,
            junction_type=self.junction_type,
            drive_position=[-450, 0],
        )
        qubit_spacing_y = 2600  # shortest y-distance between qubit centers on different sides of the feedline
        qubits_center_x = 5e3 + 400  # the x-coordinate around which qubits are centered
        y_a = float(self.feedline_y) + qubit_spacing_y / 2
        qb0_refpoints = self._produce_qubit(qubit, qubits_center_x, y_a, 2, "qb_0")
        return (qb0_refpoints,)

    def _produce_readout_resonator(self, total_length, coupling_length, pos_cplr, above_feedline, resonator_index=None):
        """Produces a readout resonator coupled to a qubit.

        The resonator starts from the feedline-side shorted end, goes along the feedline coupling section, and finally
        meanders to the qubit coupler port.

        Args:
            total_length: A float defining the total length of the resonator waveguide.
            coupling_length: A float defining the length of the part of the resonator coupled to the feedline.
            pos_cplr: A DPoint defining the qubit coupler port, which is the end of the resonator meander.
            above_feedline: A boolean value telling if the qubit is above the feedline or not.

        """
        # We define a factor depending on which side of the feedline the qubit is on. This lets us define all resonators
        # in the same way.
        if above_feedline:
            factor = 1
        else:
            factor = -1
        turn_radius = float(self.readout_turn_radius)
        distance_to_feedline = float(self.readout_feedline_gap)
        feedline_y = float(self.feedline_y)
        feedline_coupling_y = feedline_y + factor * distance_to_feedline
        short_end_x = pos_cplr.x - (coupling_length + 2 * turn_radius)
        short_end = pya.DPoint(
            short_end_x,
            feedline_y + factor * distance_to_feedline + factor * 2 * turn_radius,
        )
        meander_start = pya.DPoint(
            pos_cplr.x,
            feedline_y + factor * distance_to_feedline + factor * 2 * turn_radius,
        )
        # non-meandering part of the resonator
        coupler_waveguide = self._produce_waveguide(
            [
                short_end,
                pya.DPoint(short_end_x, feedline_coupling_y),
                pya.DPoint(pos_cplr.x, feedline_coupling_y),
                meander_start,
            ],
            term1=0,
            turn_radius=turn_radius,
        )
        if resonator_index is not None:
            self.refpoints[f"readout_{resonator_index}_short"] = short_end
        len_coupler = coupler_waveguide.length()
        # meandering part of the resonator
        meander_length = total_length - len_coupler
        w = float(self.readout_meander_width)
        num_meanders = _get_num_meanders(meander_length, turn_radius, w)
        direct_meander_length = meander_start.distance(pos_cplr)
        max_meanders = max(1, int(direct_meander_length / (2 * turn_radius) - 1))
        num_meanders = min(num_meanders, max_meanders)
        self.insert_cell(
            Meander,
            start_point=meander_start,
            end_point=pos_cplr,
            length=meander_length,
            meanders=num_meanders,
            r=turn_radius,
        )

    def _produce_readout_resonators(self):
        """Produces readout resonators for all qubits in the chip."""
        readout_res_lengths = [float(length) for length in self.readout_res_lengths]  # from strings to floats
        coupling_lengths = [float(length) for length in self.readout_coupling_lengths]
        if len(readout_res_lengths) < len(self.qubits_refpoints):
            raise ValueError("Need at least one readout length per qubit.")
        if len(coupling_lengths) < len(self.qubits_refpoints):
            raise ValueError("Need at least one readout coupling length per qubit.")

        for index, qubit_refpoints in enumerate(self.qubits_refpoints):
            self._produce_readout_resonator(
                readout_res_lengths[index],
                coupling_lengths[index],
                qubit_refpoints["port_cplr"],
                True,
                index,
            )

    def _produce_chargeline(self, pos_launcher, pos_port_drive, y_distance):
        """Produces a chargeline from a launcher to a qubit.

        The chargeline is defined in such a way that it works well for the geometry of the a SingleXmons chip.

        Args:
            pos_launcher: A DPoint representing the position of the launcher.
            pos_port_drive: A DPoint representing the position of "port_drive" of the qubit.
            y_distance: A float defining the y-distance of the second point of the chargeline from the launcher.

        """
        points = [pos_launcher, pya.DPoint(pos_port_drive.x, pos_launcher.y + y_distance), pos_port_drive]
        # if y_distance!=0, we use four points to define the chargeline, otherwise three points
        if y_distance != 0:
            points = [points[0]] + [pya.DPoint(pos_launcher.x, pos_launcher.y + y_distance)] + points[1:3]
        self._produce_waveguide(points, term2=self.b)

    def _produce_chargelines(self):
        """Produces a chargeline for the single qubit."""
        if not self.qubits_refpoints:
            return
        self._produce_chargeline(
            self.launchers["E"][0], self.qubits_refpoints[0]["port_drive"], 0
        )

    def _produce_test_resonator(self, capacitor, capacitor_dtrans, res_idx):

        factor = 2 * (res_idx % 2) - 1  # -1 for resonators below feedline, +1 for resonators above feedline
        total_length = float(self.test_res_lengths[res_idx])
        turn_radius = 50

        # non-meandering part of the resonator
        pos_start = self.get_refpoints(capacitor, capacitor_dtrans)["port_a"]
        x1 = 500
        y1 = factor * 300
        y2 = factor * 100
        meander_start = pos_start + pya.DPoint(x1, y1 + y2)
        nonmeander_waveguide = self._produce_waveguide(
            [
                pos_start,
                pos_start + pya.DPoint(0, y1),
                pos_start + pya.DPoint(x1, y1),
                meander_start,
            ],
            turn_radius=turn_radius,
        )
        len_nonmeander = nonmeander_waveguide.length()

        # meandering part of the resonator
        meander_length = total_length - len_nonmeander
        w = 250
        num_meanders = _get_num_meanders(meander_length, turn_radius, w)
        self.insert_cell(
            Meander,
            start_point=meander_start,
            end_point=meander_start + pya.DPoint(0, 2 * factor * turn_radius * (num_meanders + 1)),
            length=meander_length,
            meanders=num_meanders,
            r=turn_radius,
        )

    def _produce_feedline(self, x_distance):
        """Produces a feedline for a SingleXmons chip.

        The feedline is a straight waveguide connecting launcher "W" to launcher "E".

        Args:
            x_distance: Kept for compatibility with the previous launcher dogleg feedline.

        """
        self._produce_waveguide(
            [
                self.launchers["W"][0],
                self.launchers["E"][0],
            ]
        )

    def _produce_feedline_and_test_resonators(self, x_distance):
        """Produces a feedline and test resonators for a SingleXmons chip.

        The feedline is a straight waveguide connecting launcher "W" to launcher "E".
        There are four test resonators, located between the qubit pairs.

        Args:
            x_distance: Kept for compatibility with the previous launcher dogleg feedline.

        """
        x_offset = -700
        feedline_y = float(self.feedline_y)
        test_resonator_positions = [
            pya.DPoint(
                (self.qubits_refpoints[3]["base"].x + self.qubits_refpoints[4]["base"].x) / 2 + x_offset, feedline_y
            ),
            pya.DPoint(
                (self.qubits_refpoints[1]["base"].x + self.qubits_refpoints[0]["base"].x) / 2 + x_offset, feedline_y
            ),
            pya.DPoint(
                (self.qubits_refpoints[5]["base"].x + self.qubits_refpoints[4]["base"].x) / 2 + x_offset, feedline_y
            ),
            pya.DPoint(
                (self.qubits_refpoints[2]["base"].x + self.qubits_refpoints[1]["base"].x) / 2 + x_offset, feedline_y
            ),
        ]

        # feedline couplings with test resonators

        cell_cross = self.add_element(
            WaveguideCoplanarSplitter,
            **t_cross_parameters(a=self.a, b=self.b, a2=self.a, b2=self.b, length_extra_side=2 * self.a),
        )
        inst_crosses = []

        for i in range(4):
            # Cross
            cross_trans = pya.DTrans(2 * (i % 2), False, test_resonator_positions[i])
            inst_cross, _ = self.insert_cell(cell_cross, cross_trans)
            inst_crosses.append(inst_cross)
            cross_refpoints_abs = self.get_refpoints(cell_cross, inst_crosses[i].dtrans)

            # Coupler
            cplr_params = cap_params(float(self.n_fingers[i]), float(self.l_fingers[i]), self.type_coupler[i])
            cplr = self.add_element(**cplr_params)
            cplr_refpoints_rel = self.get_refpoints(cplr)
            if i % 2 == 0:
                cplr_pos = cross_refpoints_abs["port_bottom"] - pya.DTrans.R90 * cplr_refpoints_rel["port_b"]
            else:
                cplr_pos = cross_refpoints_abs["port_bottom"] + pya.DTrans.R90 * cplr_refpoints_rel["port_b"]
            cplr_dtrans = pya.DTrans(2 * (i % 2) + 1, False, cplr_pos.x, cplr_pos.y)
            self.insert_cell(cplr, cplr_dtrans)

            self._produce_test_resonator(cplr, cplr_dtrans, i)

        # feedline

        self._produce_waveguide(
            [
                self.launchers["W"][0],
                self.get_refpoints(cell_cross, inst_crosses[0].dtrans)["port_left"],
            ]
        )
        self._produce_waveguide(
            [
                self.get_refpoints(cell_cross, inst_crosses[0].dtrans)["port_right"],
                self.get_refpoints(cell_cross, inst_crosses[1].dtrans)["port_right"],
            ]
        )
        self._produce_waveguide(
            [
                self.get_refpoints(cell_cross, inst_crosses[1].dtrans)["port_left"],
                self.get_refpoints(cell_cross, inst_crosses[2].dtrans)["port_left"],
            ]
        )
        self._produce_waveguide(
            [
                self.get_refpoints(cell_cross, inst_crosses[2].dtrans)["port_right"],
                self.get_refpoints(cell_cross, inst_crosses[3].dtrans)["port_right"],
            ]
        )
        self._produce_waveguide(
            [
                self.get_refpoints(cell_cross, inst_crosses[3].dtrans)["port_left"],
                self.launchers["E"][0],
            ]
        )
