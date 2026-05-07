"""SCDevice standalone double-pads qubit PCell."""

import math

from kqcircuits.elements.element import Element
from kqcircuits.junctions.manhattan import Manhattan
from kqcircuits.junctions.squid import Squid
from kqcircuits.util.parameters import Param, pdt, add_parameters_from
from kqcircuits.pya_resolver import pya
from kqcircuits.qubits.qubit import Qubit
from kqcircuits.util.refpoints import WaveguideToSimPort, JunctionSimPort
from scdevice_pcells.junctions import SQNL_MANHATTAN_SINGLE_JUNCTION
from scdevice_pcells.junctions.manhattan_single_junction_v2 import (
    SqnlManhattanSingleJunctionV2,
)


@add_parameters_from(Squid, junction_type=SQNL_MANHATTAN_SINGLE_JUNCTION)
@add_parameters_from(SqnlManhattanSingleJunctionV2)
@add_parameters_from(Manhattan)
class DoublePadsSQNL(Qubit):
    """SCDevice double-pads qubit with local junction customization hooks."""

    ground_gap = Param(
        pdt.TypeList, "Width, height of the ground gap (µm, µm)", [900, 900]
    )
    ground_gap_r = Param(pdt.TypeDouble, "Ground gap rounding radius", 50, unit="μm")
    coupler_extent = Param(
        pdt.TypeList, "Width, height of the coupler (µm, µm)", [150, 20]
    )
    coupler_r = Param(pdt.TypeDouble, "Coupler rounding radius", 10, unit="μm")
    coupler_a = Param(
        pdt.TypeDouble,
        "Width of the coupler waveguide center conductor",
        Element.a,
        unit="μm",
    )
    coupler_offset = Param(
        pdt.TypeDouble, "Distance from first qubit island to coupler", 100, unit="μm"
    )
    squid_offset = Param(
        pdt.TypeDouble, "Offset between SQUID center and qubit center", 0, unit="μm"
    )
    island1_extent = Param(
        pdt.TypeList, "Width, height of the first qubit island (µm, µm)", [800, 150]
    )
    island1_r = Param(
        pdt.TypeDouble, "First qubit island rounding radius", 50, unit="μm"
    )
    island2_extent = Param(
        pdt.TypeList, "Width, height of the second qubit island (µm, µm)", [800, 150]
    )
    island2_r = Param(
        pdt.TypeDouble, "Second qubit island rounding radius", 50, unit="μm"
    )
    drive_position = Param(
        pdt.TypeList, "Coordinate for the drive port (µm, µm)", [-450, 0]
    )
    island1_taper_width = Param(
        pdt.TypeDouble,
        "First qubit island tapering width on the island side",
        10,
        unit="µm",
    )
    island1_taper_junction_width = Param(
        pdt.TypeDouble,
        "First qubit island tapering width on the junction side",
        2,
        unit="µm",
    )
    island2_taper_width = Param(
        pdt.TypeDouble,
        "Second qubit island tapering width on the island side",
        10,
        unit="µm",
    )
    island2_taper_junction_width = Param(
        pdt.TypeDouble,
        "Second qubit island tapering width on the junction side",
        2,
        unit="µm",
    )

    island_island_gap = Param(
        pdt.TypeDouble, "Island to island gap distance", 40, unit="µm"
    )
    with_squid = Param(pdt.TypeBoolean, "Boolean whether to include the squid", True)

    def build(self):
        # Qubit base
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

        # SQUID
        # Create temporary SQUID cell to calculate SQUID height
        temp_squid_cell = self.add_element(Squid, junction_type=self.junction_type)
        temp_squid_ref = self.get_refpoints(temp_squid_cell)
        upper_attach, lower_attach = self._squid_attach_points(temp_squid_ref)
        squid_height = upper_attach.y - lower_attach.y
        if squid_height <= 0:
            raise ValueError(
                "Upper SQUID attach refpoint must be above lower SQUID attach refpoint."
            )
        if float(self.island_island_gap) <= squid_height:
            raise ValueError(
                "Island to island gap must be larger than SQUID attach point separation."
            )

        squid_transf = pya.DCplxTrans(
            1,
            0,
            False,
            pya.DVector(
                -upper_attach.x,
                self.squid_offset - (upper_attach.y + lower_attach.y) / 2,
            ),
        )
        upper_attach = squid_transf * upper_attach
        lower_attach = squid_transf * lower_attach

        if self.with_squid:
            self.produce_squid(squid_transf)

        taper_height = (self.island_island_gap - squid_height) / 2

        # First island
        island1_region = self._build_island1(upper_attach, taper_height)

        # Second island
        island2_region = self._build_island2(lower_attach, taper_height)

        # Coupler gap
        coupler_region = self._build_coupler(
            upper_attach.y + taper_height + float(self.island1_extent[1])
        )

        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(
            ground_gap_region - coupler_region - island1_region - island2_region
        )

        # Protection
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

        # Coupler port
        self.add_port(
            "cplr",
            pya.DPoint(0, float(self.ground_gap[1]) / 2),
            direction=pya.DVector(pya.DPoint(0, float(self.ground_gap[1]))),
        )

        # Drive port
        self.add_port(
            "drive",
            pya.DPoint(float(self.drive_position[0]), float(self.drive_position[1])),
            direction=pya.DVector(
                float(self.drive_position[0]), float(self.drive_position[1])
            ),
        )

        # Probepoints
        self.refpoints["probe_island_1"] = pya.DPoint(
            0, upper_attach.y + taper_height + float(self.island1_extent[1]) / 2
        )
        self.refpoints["probe_island_2"] = pya.DPoint(
            0, lower_attach.y - taper_height - float(self.island2_extent[1]) / 2
        )
        self.refpoints["junction_attach_island_1"] = upper_attach
        self.refpoints["junction_attach_island_2"] = lower_attach

    @staticmethod
    def _squid_attach_points(refpoints):
        if "attach_island_1" in refpoints and "attach_island_2" in refpoints:
            return refpoints["attach_island_1"], refpoints["attach_island_2"]
        return refpoints["port_common"], refpoints["origin_squid"]

    def _build_coupler(self, first_island_top_edge):
        coupler_top_edge = (
            first_island_top_edge + self.coupler_offset + float(self.coupler_extent[1])
        )
        coupler_polygon = pya.DPolygon(
            [
                pya.DPoint(-float(self.coupler_extent[0]) / 2, coupler_top_edge),
                pya.DPoint(
                    -float(self.coupler_extent[0]) / 2,
                    first_island_top_edge + self.coupler_offset,
                ),
                pya.DPoint(
                    float(self.coupler_extent[0]) / 2,
                    first_island_top_edge + self.coupler_offset,
                ),
                pya.DPoint(float(self.coupler_extent[0]) / 2, coupler_top_edge),
            ]
        )
        coupler_region = pya.Region(coupler_polygon.to_itype(self.layout.dbu))
        coupler_region.round_corners(
            self.coupler_r / self.layout.dbu, self.coupler_r / self.layout.dbu, self.n
        )
        coupler_path_polygon = pya.DPolygon(
            [
                pya.DPoint(-self.coupler_a / 2, (float(self.ground_gap[1]) / 2)),
                pya.DPoint(self.coupler_a / 2, (float(self.ground_gap[1]) / 2)),
                pya.DPoint(self.coupler_a / 2, coupler_top_edge),
                pya.DPoint(-self.coupler_a / 2, coupler_top_edge),
            ]
        )
        coupler_path = pya.Region(coupler_path_polygon.to_itype(self.layout.dbu))
        return coupler_region + coupler_path

    def _build_island1(self, attach_point, taper_height):
        island1_bottom = attach_point.y
        island1_edge = island1_bottom + taper_height
        island1_polygon = pya.DPolygon(
            [
                pya.DPoint(
                    -float(self.island1_extent[0]) / 2,
                    island1_edge + float(self.island1_extent[1]),
                ),
                pya.DPoint(
                    float(self.island1_extent[0]) / 2,
                    island1_edge + float(self.island1_extent[1]),
                ),
                pya.DPoint(float(self.island1_extent[0]) / 2, island1_edge),
                pya.DPoint(-float(self.island1_extent[0]) / 2, island1_edge),
            ]
        )
        island1_region = pya.Region(island1_polygon.to_itype(self.layout.dbu))
        island1_region.round_corners(
            self.island1_r / self.layout.dbu, self.island1_r / self.layout.dbu, self.n
        )
        island1_taper = pya.Region(
            pya.DPolygon(
                [
                    pya.DPoint(self.island1_taper_width / 2, island1_edge),
                    pya.DPoint(
                        attach_point.x + self.island1_taper_junction_width / 2,
                        attach_point.y,
                    ),
                    pya.DPoint(
                        attach_point.x - self.island1_taper_junction_width / 2,
                        attach_point.y,
                    ),
                    pya.DPoint(-self.island1_taper_width / 2, island1_edge),
                ]
            ).to_itype(self.layout.dbu)
        )

        return island1_region + island1_taper

    def _build_island2(self, attach_point, taper_height):
        island2_top = attach_point.y
        island2_edge = island2_top - taper_height
        island2_polygon = pya.DPolygon(
            [
                pya.DPoint(
                    -float(self.island2_extent[0]) / 2,
                    island2_edge - float(self.island2_extent[1]),
                ),
                pya.DPoint(
                    float(self.island2_extent[0]) / 2,
                    island2_edge - float(self.island2_extent[1]),
                ),
                pya.DPoint(float(self.island2_extent[0]) / 2, island2_edge),
                pya.DPoint(-float(self.island2_extent[0]) / 2, island2_edge),
            ]
        )
        island2_region = pya.Region(island2_polygon.to_itype(self.layout.dbu))
        island2_region.round_corners(
            self.island2_r / self.layout.dbu, self.island2_r / self.layout.dbu, self.n
        )
        island2_taper = pya.Region(
            pya.DPolygon(
                [
                    pya.DPoint(self.island2_taper_width / 2, island2_edge),
                    pya.DPoint(
                        attach_point.x + self.island2_taper_junction_width / 2,
                        attach_point.y,
                    ),
                    pya.DPoint(
                        attach_point.x - self.island2_taper_junction_width / 2,
                        attach_point.y,
                    ),
                    pya.DPoint(-self.island2_taper_width / 2, island2_edge),
                ]
            ).to_itype(self.layout.dbu)
        )
        return island2_region + island2_taper

    @classmethod
    def get_sim_ports(cls, simulation):  # pylint: disable=unused-argument
        return [
            JunctionSimPort(floating=True),
            WaveguideToSimPort("port_cplr", side="top", a=simulation.coupler_a),
        ]
