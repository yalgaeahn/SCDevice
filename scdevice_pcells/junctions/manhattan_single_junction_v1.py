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


# Jotmang 나중에 다시 도전


from kqcircuits.junctions.junction import Junction
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


class SqnlManhattanSingleJunctionV1Archive:
    """Orthogonal Manhattan single-junction PCell for SCDevice."""

    finger_overshoot = Param(
        pdt.TypeDouble, "Length of fingers after the junction.", 0.5, unit="um"
    )
    include_base_metal_gap = Param(
        pdt.TypeBoolean, "Include base metal gap layer.", True
    )
    include_base_metal_addition = Param(
        pdt.TypeBoolean, "Include base metal addition layer.", False
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
        pdt.TypeDouble, "Length of fingers inside the pads.", 0.5, unit="um"
    )
    height = Param(pdt.TypeDouble, "Height of the junction element.", 10.0, unit="um")
    width = Param(pdt.TypeDouble, "Width of the junction element.", 10.0, unit="um")
    pad_height = Param(pdt.TypeDouble, "Height of the junction pad.", 1.0, unit="um")
    pad_width = Param(pdt.TypeDouble, "Width of the junction pad.", 1.0, unit="um")
    pad_to_pad_separation = Param(pdt.TypeDouble, "Pad separation.", 3.0, unit="um")
    x_offset = Param(pdt.TypeDouble, "Horizontal junction offset.", 0, unit="um")
    pad_rounding_radius = Param(
        pdt.TypeDouble, "Rounding radius of the junction pad.", 0.5, unit="um"
    )

    def build(self):
        self.produce_manhattan_junction()

    def produce_manhattan_junction(self):
        rounding_params = {
            "rinner": self.pad_rounding_radius,
            "router": self.pad_rounding_radius,
            "n": 64,
        }

        self._junction_center = pya.DPoint(0, self.height / 2)
        self._lead_top = pya.DPoint(0, self.height)
        self._lead_right = pya.DPoint(self.width / 2, self.height / 2)

        vertical_shapes, horizontal_shapes, shadow_shapes = (
            self._make_orthogonal_junction(rounding_params)
        )

        self._add_shapes(vertical_shapes, "SIS_junction")
        self._add_shapes(
            horizontal_shapes,
            "SIS_junction_2" if self.separate_junctions else "SIS_junction",
        )
        self._add_shapes(shadow_shapes, "SIS_shadow")
        self._produce_ground_metal_shapes()
        self._produce_ground_grid_avoidance()
        self._add_refpoints()

    def _make_orthogonal_junction(self, rounding_params):
        """Create the two orthogonal single-junction electrodes."""
        vertical_width, horizontal_width = self._electrode_widths()
        center = self._junction_center
        top = self._lead_top
        right = self._lead_right

        vertical_shapes = []
        horizontal_shapes = []
        shadow_shapes = []

        top_pad = (
            top.x - self.pad_width / 2,
            top.y - self.pad_height,
            top.x + self.pad_width / 2,
            top.y,
        )
        vertical_arm = (
            center.x - vertical_width / 2,
            center.y - self.finger_overshoot,
            center.x + vertical_width / 2,
            min(top.y, top.y - self.pad_height + self.finger_overlap),
        )
        right_pad = (
            right.x - self.pad_height,
            right.y - self.pad_width / 2,
            right.x,
            right.y + self.pad_width / 2,
        )
        horizontal_arm = (
            center.x - self.finger_overshoot,
            center.y - horizontal_width / 2,
            min(right.x, right.x - self.pad_height + self.finger_overlap),
            center.y + horizontal_width / 2,
        )

        geometry_rects = [top_pad, vertical_arm, right_pad, horizontal_arm]
        self._geometry_bounds = self._bounds_from_rects(geometry_rects)
        self._addition_rects = geometry_rects

        self._append_rect(vertical_shapes, top_pad, rounding_params)
        self._append_rect(vertical_shapes, vertical_arm)
        self._append_rect(horizontal_shapes, right_pad, rounding_params)
        self._append_rect(horizontal_shapes, horizontal_arm)

        for rect in geometry_rects:
            self._append_rect(
                shadow_shapes, self._expanded_rect(rect, self.shadow_margin)
            )

        return vertical_shapes, horizontal_shapes, shadow_shapes

    def _electrode_widths(self):
        """Return widths for the vertical and horizontal junction electrodes."""
        vertical_width = self.junction_width
        horizontal_width = self.junction_width
        if self.mirror_offset:
            vertical_width += self.offset_compensation
        else:
            horizontal_width += self.offset_compensation
        minimum_width = self.layout.dbu
        return max(vertical_width, minimum_width), max(horizontal_width, minimum_width)

    def _add_shapes(self, shapes, layer):
        """Merge shapes into a region and add it to layer."""
        if not shapes:
            return
        region = pya.Region(shapes).merged()
        self.cell.shapes(self.get_layer(layer)).insert(region)

    def _add_refpoints(self):
        """Add junction terminal refpoints and the KQCircuits-compatible common port."""
        center = self._junction_center
        top = self._lead_top
        right = self._lead_right

        self.refpoints["junction_center"] = pya.DPoint(center.x, center.y)
        self.refpoints["c"] = pya.DPoint(center.x, center.y)
        self.refpoints["lead_top"] = pya.DPoint(top.x, top.y)
        self.refpoints["lead_right"] = pya.DPoint(right.x, right.y)
        self.refpoints["terminal_1"] = pya.DPoint(top.x, top.y)
        self.refpoints["terminal_2"] = pya.DPoint(right.x, right.y)
        self.refpoints["origin_squid"] = pya.DPoint(top.x, top.y)
        self.add_port("common", pya.DPoint(right.x, right.y))

    def _produce_ground_metal_shapes(self):
        """Produce base-metal clearance around the orthogonal junction geometry."""
        if self.include_base_metal_addition:
            addition_shapes = [
                self._rect_polygon(rect).to_itype(self.layout.dbu)
                for rect in self._addition_rects
            ]
            self.cell.shapes(self.get_layer("base_metal_addition")).insert(
                pya.Region(addition_shapes).merged()
            )

        if self.include_base_metal_gap:
            gap_bounds = self._expanded_rect(self._geometry_bounds, self.shadow_margin)
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(
                self._rect_polygon(gap_bounds).to_itype(self.layout.dbu)
            )

    def _produce_ground_grid_avoidance(self):
        """Add ground grid avoidance around the actual junction envelope."""
        protection_bounds = self._expanded_rect(
            self._geometry_bounds, self.shadow_margin + self.margin
        )
        self.add_protection(self._rect_polygon(protection_bounds))

    def _append_rect(self, polygon_list, rect, rounding_params=None):
        """Append an integer rectangle polygon, optionally rounded."""
        polygon = self._rect_polygon(rect)
        if rounding_params is None:
            polygon_list.append(polygon.to_itype(self.layout.dbu))
        else:
            self._round_corners_and_append(polygon, polygon_list, rounding_params)

    @staticmethod
    def _rect_polygon(rect):
        """Return a DPolygon for a rectangle described by left, bottom, right, top."""
        left, bottom, right, top = rect
        left, right = sorted((left, right))
        bottom, top = sorted((bottom, top))
        return pya.DPolygon(
            [
                pya.DPoint(left, bottom),
                pya.DPoint(right, bottom),
                pya.DPoint(right, top),
                pya.DPoint(left, top),
            ]
        )

    @staticmethod
    def _expanded_rect(rect, margin):
        """Expand a rectangle tuple by ``margin`` on all sides."""
        left, bottom, right, top = rect
        return left - margin, bottom - margin, right + margin, top + margin

    @staticmethod
    def _bounds_from_rects(rects):
        """Return the bounding rectangle of several rectangle tuples."""
        return (
            min(rect[0] for rect in rects),
            min(rect[1] for rect in rects),
            max(rect[2] for rect in rects),
            max(rect[3] for rect in rects),
        )

    def _round_corners_and_append(self, polygon, polygon_list, rounding_params):
        """Round polygon corners and append the integer polygon to ``polygon_list``."""
        polygon = polygon.round_corners(
            rounding_params["rinner"], rounding_params["router"], rounding_params["n"]
        )
        polygon_list.append(polygon.to_itype(self.layout.dbu))
