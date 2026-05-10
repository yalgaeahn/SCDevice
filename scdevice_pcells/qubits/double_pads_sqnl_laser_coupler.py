"""Laser-writer footprint for the SQNL double-pads qubit coupler."""

import math

from kqcircuits.pya_resolver import pya
from kqcircuits.util.refpoints import WaveguideToSimPort

from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL


class DoublePadsSQNLLaserCoupler(DoublePadsSQNL):
    """DoublePadsSQNL footprint without double pads or junction metal.

    This keeps the qubit ground-gap cutout and the readout coupler neck/paddle
    so readout resonators can terminate at the normal ``port_cplr`` location.
    """

    def build(self):
        ground_gap_points = [
            pya.DPoint(float(self.ground_gap[0]) / 2, float(self.ground_gap[1]) / 2),
            pya.DPoint(float(self.ground_gap[0]) / 2, -float(self.ground_gap[1]) / 2),
            pya.DPoint(-float(self.ground_gap[0]) / 2, -float(self.ground_gap[1]) / 2),
            pya.DPoint(-float(self.ground_gap[0]) / 2, float(self.ground_gap[1]) / 2),
        ]
        ground_gap_polygon = pya.DPolygon(ground_gap_points)
        ground_gap_region = pya.Region(ground_gap_polygon.to_itype(self.layout.dbu))
        ground_gap_region.round_corners(
            self.ground_gap_r / self.layout.dbu,
            self.ground_gap_r / self.layout.dbu,
            self.n,
        )

        first_island_top_edge = (
            float(self.squid_offset)
            + float(self.island_island_gap) / 2
            + float(self.island1_extent[1])
        )
        coupler_region = self._build_coupler(first_island_top_edge)

        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(
            ground_gap_region - coupler_region
        )

        protection_polygon = pya.DPolygon(
            [
                p
                + pya.DVector(
                    math.copysign(self.margin, p.x), math.copysign(self.margin, p.y)
                )
                for p in ground_gap_points
            ]
        )
        protection_region = pya.Region(protection_polygon.to_itype(self.layout.dbu))
        protection_region.round_corners(
            (self.ground_gap_r + self.margin) / self.layout.dbu,
            (self.ground_gap_r + self.margin) / self.layout.dbu,
            self.n,
        )
        self.add_protection(protection_region)

        self.add_port(
            "cplr",
            pya.DPoint(0, float(self.ground_gap[1]) / 2),
            direction=pya.DVector(pya.DPoint(0, float(self.ground_gap[1]))),
        )

    @classmethod
    def get_sim_ports(cls, simulation):  # pylint: disable=unused-argument
        return [
            WaveguideToSimPort("port_cplr", side="top", a=simulation.coupler_a),
        ]
