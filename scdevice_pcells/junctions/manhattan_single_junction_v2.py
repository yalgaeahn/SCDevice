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


TAPER_ATTACH_FINGER_OVERLAP = 1.0


class SqnlManhattanSingleJunctionV2(Junction):
    """Lead-only SCDevice V2 copy of the KQCircuits Manhattan single-junction PCell."""

    junction_width = Param(
        pdt.TypeDouble,
        "Junction width for code generated element",
        0.2,
        unit="um",
        docstring="Junction width (only used for code generated element)",
    )
    finger_overshoot = Param(
        pdt.TypeDouble, "Length of fingers after the junction.", 1.0, unit="um"
    )
    include_base_metal_gap = Param(
        pdt.TypeBoolean, "Include base metal gap layer.", True
    )
    include_base_metal_addition = Param(
        pdt.TypeBoolean, "Ignored in lead-only V2.", False
    )
    include_contact_pads = Param(
        pdt.TypeBoolean, "Include SIS contact pads.", True
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
        pdt.TypeDouble, "Length of fingers inside the pads.", 3.0, unit="um"
    )
    height = Param(pdt.TypeDouble, "Height of the junction element.", 22.0, unit="um")
    width = Param(pdt.TypeDouble, "Width of the junction element.", 22.0, unit="um")
    pad_height = Param(pdt.TypeDouble, "Height of the junction pad.", 3.0, unit="um")
    pad_width = Param(pdt.TypeDouble, "Width of the junction pad.", 3.0, unit="um")
    pad_to_pad_separation = Param(pdt.TypeDouble, "Pad separation.", 6.0, unit="um")
    x_offset = Param(pdt.TypeDouble, "Horizontal junction offset.", -1, unit="um")
    pad_rounding_radius = Param(
        pdt.TypeDouble, "Rounding radius of the junction pad.", 1.0, unit="um"
    )

    def build(self):
        self.produce_manhattan_junction()

    def produce_manhattan_junction(self):
        self._make_junction(
            pya.DPoint(0, self.height / 2 + 2.8), self.height / 2 - 5, 0
        )

        if self.include_contact_pads:
            self._produce_contact_pads()

        self._produce_shadow_shapes()
        self._produce_ground_metal_shapes()
        self._produce_ground_grid_avoidance()
        self._add_refpoints()

    def _produce_contact_pads(self):
        """Produce rounded SIS contact pads centered on drawn lead ends."""
        rounding_params = {
            "rinner": self.pad_rounding_radius,
            "router": self.pad_rounding_radius,
            "n": 64,
        }

        junction_shapes = []
        for center in (self._contact_pad_bottom, self._contact_pad_top):
            self._round_corners_and_append(
                self._contact_pad_polygon(center), junction_shapes, rounding_params
            )
        self._add_shapes(junction_shapes, "SIS_junction")

    def _contact_pad_polygon(self, center, margin=0):
        """Return a rectangular contact pad centered at ``center``."""
        half_width = self.pad_width / 2 + margin
        half_height = self.pad_height / 2 + margin
        return pya.DPolygon(
            [
                pya.DPoint(center.x - half_width, center.y - half_height),
                pya.DPoint(center.x + half_width, center.y - half_height),
                pya.DPoint(center.x + half_width, center.y + half_height),
                pya.DPoint(center.x - half_width, center.y + half_height),
            ]
        )

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

        def finger_points(size, finger_overlap):
            pl = finger_overlap * sqrt(0.5) + 0.2
            return [
                pya.DPoint(top_corner.x + pl, top_corner.y + size + pl),
                pya.DPoint(top_corner.x + size + pl, top_corner.y + pl),
                pya.DPoint(jx - fo, jy - fo - size),
                pya.DPoint(jx - fo - size, jy - fo),
            ]

        def lead_polygons(finger_overlap, x_offset):
            finger_bottom = pya.DTrans(-jx, -jy + x_offset) * pya.DPolygon(
                finger_points(ddb, finger_overlap)
            )
            finger_top = pya.DTrans(-jx + x_offset, -jy) * pya.DPolygon(
                finger_points(ddt, finger_overlap)
            )
            return [
                pya.DTrans(jx - finger_margin, jy) * finger_top,
                pya.DTrans(0, False, jx - 2 * top_corner.x, jy) * finger_top,
                pya.DTrans(3, False, jx - finger_margin, jy + 2.2)
                * finger_bottom,
                pya.DTrans(3, False, jx - 2 * top_corner.x, jy + 2.2)
                * finger_bottom,
            ]

        junction_polygons = lead_polygons(self.finger_overlap, self.x_offset)
        attach_polygons = lead_polygons(TAPER_ATTACH_FINGER_OVERLAP, 0)

        junction_region = pya.Region(
            [polygon.to_itype(self.layout.dbu) for polygon in junction_polygons]
        ).merged()
        layer_name = "SIS_junction_2" if self.separate_junctions else "SIS_junction"
        self.cell.shapes(self.get_layer(layer_name)).insert(junction_region)

        self._junction_region = junction_region
        self._junction_bounds = junction_region.bbox().to_dtype(self.layout.dbu)
        self._lead_top = self._outer_short_edge_center(attach_polygons, upper=True)
        self._lead_bottom = self._outer_short_edge_center(
            attach_polygons, upper=False
        )
        # Contact pads and qubit tapers use the fixed logical attach geometry;
        # only the drawn fingers grow with finger_overlap.
        self._contact_pad_top = pya.DPoint(self._lead_top.x, self._lead_top.y)
        self._contact_pad_bottom = pya.DPoint(
            self._lead_bottom.x, self._lead_bottom.y
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

    def _add_shapes(self, shapes, layer):
        """Merge shapes into a region and add it to layer."""
        if not shapes:
            return
        self.cell.shapes(self.get_layer(layer)).insert(pya.Region(shapes).merged())

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
        """Produce rounded shadow envelopes around the fixed contact pads."""
        rounding_params = {
            "rinner": self.pad_rounding_radius,
            "router": self.pad_rounding_radius,
            "n": 64,
        }

        shadow_shapes = []
        for center in (self._contact_pad_bottom, self._contact_pad_top):
            self._round_corners_and_append(
                self._contact_pad_polygon(center, self.shadow_margin),
                shadow_shapes,
                rounding_params,
            )
        self._add_shapes(shadow_shapes, "SIS_shadow")

    def _produce_ground_metal_shapes(self):
        """Leave base-metal gap ownership to the parent qubit geometry."""

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

    def _round_corners_and_append(self, polygon, polygon_list, rounding_params):
        """Round polygon corners, convert to integer coordinates, and append."""
        polygon = polygon.round_corners(
            rounding_params["rinner"],
            rounding_params["router"],
            rounding_params["n"],
        )
        polygon_list.append(polygon.to_itype(self.layout.dbu))
