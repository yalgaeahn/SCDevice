# This code is part of KQCircuits
# Copyright (C) 2022 IQM Finland Oy
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


from math import sqrt

from kqcircuits.junctions.junction import Junction
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


class SqnlManhattanSingleJunctionV2(Junction):
    """Lead-only SCDevice V2 copy of the KQCircuits Manhattan single-junction PCell."""

    finger_overshoot = Param(
        pdt.TypeDouble, "Length of fingers after the junction.", 1.0, unit="um"
    )
    include_base_metal_gap = Param(
        pdt.TypeBoolean, "Include base metal gap layer.", True
    )
    include_base_metal_addition = Param(
        pdt.TypeBoolean, "Ignored in lead-only V2.", False
    )
    shadow_margin = Param(
        pdt.TypeDouble, "Shadow layer margin near the the pads.", 0.5, unit="um"
    )
    separate_junctions = Param(pdt.TypeBoolean, "Junctions to separate layer.", True)
    offset_compensation = Param(
        pdt.TypeDouble, "Junction lead offset from junction width", 0, unit="um"
    )
    mirror_offset = Param(
        pdt.TypeBoolean, "Move the junction lead offset to the other lead", False
    )
    finger_overlap = Param(
        pdt.TypeDouble, "Length of fingers inside the pads.", 1.0, unit="um"
    )
    height = Param(pdt.TypeDouble, "Height of the junction element.", 22.0, unit="um")
    width = Param(pdt.TypeDouble, "Width of the junction element.", 22.0, unit="um")
    pad_height = Param(pdt.TypeDouble, "Height of the junction pad.", 6.0, unit="um")
    pad_width = Param(pdt.TypeDouble, "Width of the junction pad.", 12.0, unit="um")
    pad_to_pad_separation = Param(pdt.TypeDouble, "Pad separation.", 6.0, unit="um")
    x_offset = Param(pdt.TypeDouble, "Horizontal junction offset.", 0, unit="um")
    pad_rounding_radius = Param(
        pdt.TypeDouble, "Rounding radius of the junction pad.", 0.5, unit="um"
    )

    def build(self):
        self.produce_manhattan_junction()

    def produce_manhattan_junction(self):
        self._make_junction(
            pya.DPoint(0, self.height / 2 + 2.8), self.height / 2 - 5, 0
        )
        self._produce_shadow_shapes()
        self._produce_ground_metal_shapes()
        self._produce_ground_grid_avoidance()
        self._add_refpoints()

    def _make_junction(self, top_corner, b_corner_y, finger_margin=0):
        """Create junction fingers and add them to some SIS layer."""
        jx = top_corner.x - (top_corner.y - b_corner_y) / 2
        jy = (top_corner.y + b_corner_y) / 2
        ddb = self.junction_width * sqrt(0.5)
        ddt = self.junction_width * sqrt(0.5)
        if self.mirror_offset:
            ddt += self.offset_compensation * sqrt(0.5)
        else:
            ddb += self.offset_compensation * sqrt(0.5)
        fo = self.finger_overshoot * sqrt(0.5) - 1.1
        pl = self.finger_overlap * sqrt(0.5) + 0.2

        def finger_points(size):
            return [
                pya.DPoint(top_corner.x + pl, top_corner.y + size + pl),
                pya.DPoint(top_corner.x + size + pl, top_corner.y + pl),
                pya.DPoint(jx - fo, jy - fo - size),
                pya.DPoint(jx - fo - size, jy - fo),
            ]

        finger_bottom = pya.DTrans(-jx, -jy + self.x_offset) * pya.DPolygon(
            finger_points(ddb)
        )
        finger_top = pya.DTrans(-jx + self.x_offset, -jy) * pya.DPolygon(
            finger_points(ddt)
        )

        junction_polygons = [
            pya.DTrans(jx - finger_margin, jy) * finger_top,
            pya.DTrans(0, False, jx - 2 * top_corner.x, jy) * finger_top,
            pya.DTrans(3, False, jx - finger_margin, jy + 2.2) * finger_bottom,
            pya.DTrans(3, False, jx - 2 * top_corner.x, jy + 2.2) * finger_bottom,
        ]

        junction_region = pya.Region(
            [polygon.to_itype(self.layout.dbu) for polygon in junction_polygons]
        ).merged()
        layer_name = "SIS_junction_2" if self.separate_junctions else "SIS_junction"
        self.cell.shapes(self.get_layer(layer_name)).insert(junction_region)

        self._junction_region = junction_region
        self._junction_bounds = junction_region.bbox().to_dtype(self.layout.dbu)
        self._lead_top = self._outer_short_edge_center(junction_polygons, upper=True)
        self._lead_bottom = self._outer_short_edge_center(
            junction_polygons, upper=False
        )
        self.refpoints["c"] = pya.DPoint(jx + 1.1 - finger_margin, jy + 1.1)

    def _outer_short_edge_center(self, polygons, upper):
        """Return the outer lead short-edge center from generated lead polygons."""
        max_edge_length = max(
            0.5,
            4 * (self.junction_width + abs(self.offset_compensation))
            + 4 * self.layout.dbu,
        )
        best_center = None
        best_y = None
        for polygon in polygons:
            points = list(polygon.each_point_hull())
            for index, point in enumerate(points):
                next_point = points[(index + 1) % len(points)]
                edge_length = point.distance(next_point)
                if edge_length > max_edge_length:
                    continue
                center = pya.DPoint(
                    (point.x + next_point.x) / 2, (point.y + next_point.y) / 2
                )
                if (
                    best_y is None
                    or (upper and center.y > best_y)
                    or (not upper and center.y < best_y)
                ):
                    best_center = center
                    best_y = center.y
        if best_center is None:
            raise ValueError("Could not determine junction lead attach refpoint.")
        return best_center

    def _add_refpoints(self):
        """Add KQ-compatible refpoints at the direct lead attach points."""
        self.refpoints["attach_island_1"] = pya.DPoint(
            self._lead_top.x, self._lead_top.y
        )
        self.refpoints["attach_island_2"] = pya.DPoint(
            self._lead_bottom.x, self._lead_bottom.y
        )
        self.refpoints["origin_squid"] = pya.DPoint(
            self._lead_bottom.x, self._lead_bottom.y
        )
        self.add_port("common", pya.DPoint(self._lead_top.x, self._lead_top.y))

    def _produce_shadow_shapes(self):
        """Produce a simple shadow envelope around the lead-only junction."""
        self.cell.shapes(self.get_layer("SIS_shadow")).insert(
            self._expanded_box(self._junction_bounds, self.shadow_margin)
        )

    def _produce_ground_metal_shapes(self):
        """Produce only base-metal gap clearance around the lead-only junction."""
        if self.include_base_metal_gap:
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(
                self._expanded_box(self._junction_bounds, self.shadow_margin)
            )

    def _produce_ground_grid_avoidance(self):
        """Add ground grid avoidance around the lead-only junction."""
        self.add_protection(
            self._expanded_box(self._junction_bounds, self.shadow_margin + self.margin)
        )

    @staticmethod
    def _expanded_box(box, margin):
        """Return a DBox expanded by ``margin``."""
        return pya.DBox(
            box.left - margin,
            box.bottom - margin,
            box.right + margin,
            box.top + margin,
        )
