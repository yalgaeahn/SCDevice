from kqcircuits.util.geometry_helper import bspline_points
from kqcircuits.util.parameters import Param, pdt, add_parameters_from
from kqcircuits.qubits.double_pads import DoublePads
from kqcircuits.pya_resolver import pya


@add_parameters_from(DoublePads, junction_type="Manhattan Single Junction")
class DoublePadsSQNL(DoublePads):
    """Double-pads qubit with spline-shaped SQNL islands."""

    island_spline = Param(
        pdt.TypeList,
        "Control points of a B-Spline that defines left half of the island",
        [-250, 20, -250, 80, -100, 100, 0, 100],
    )
    island_spline_samples = Param(
        pdt.TypeInt,
        "Number of samples taken from each island spline",
        100,
        docstring=(
            "Number of samples taken from each island spline. "
            "There is a spline for each consequent series of four control points"
        ),
    )

    def _build_island1(self, squid_height, taper_height):
        island1_bottom = self.squid_offset + squid_height / 2
        curve_start = pya.DPoint(0, island1_bottom + taper_height)
        island1_control_points = [curve_start + pya.DPoint(-self.island1_taper_width / 2, 0)] + [
            curve_start + pya.DPoint(float(self.island_spline[idx]), float(self.island_spline[idx + 1]))
            for idx in range(0, len(self.island_spline), 2)
        ]
        island1_control_points += [pya.DPoint(-p.x, p.y) for p in reversed(island1_control_points[:-1])]
        for i, point in enumerate(island1_control_points):
            self.refpoints[f"island1_control_point_{i}"] = point
        island1_polygon = pya.DPolygon(
            bspline_points(island1_control_points, self.island_spline_samples, startpoint=True, endpoint=True)
        )
        island1_region = pya.Region(island1_polygon.to_itype(self.layout.dbu))
        island1_taper = pya.Region(
            pya.DPolygon(
                [
                    # protrude taper into island in case of precision errors
                    pya.DPoint(self.island1_taper_width / 2, island1_bottom + taper_height + 1),
                    pya.DPoint(self.island1_taper_width / 2, island1_bottom + taper_height),
                    pya.DPoint(self.island1_taper_junction_width / 2, island1_bottom),
                    pya.DPoint(-self.island1_taper_junction_width / 2, island1_bottom),
                    pya.DPoint(-self.island1_taper_width / 2, island1_bottom + taper_height),
                    # protrude taper into island in case of precision errors
                    pya.DPoint(-self.island1_taper_width / 2, island1_bottom + taper_height + 1),
                ]
            ).to_itype(self.layout.dbu)
        )
        return island1_region + island1_taper

    def _build_island2(self, squid_height, taper_height):
        island2_top = self.squid_offset - squid_height / 2
        curve_start = pya.DPoint(0, island2_top - taper_height)
        island2_control_points = [curve_start + pya.DPoint(-self.island2_taper_width / 2, 0)] + [
            curve_start + pya.DPoint(float(self.island_spline[idx]), -float(self.island_spline[idx + 1]))
            for idx in range(0, len(self.island_spline), 2)
        ]
        island2_control_points += [pya.DPoint(-p.x, p.y) for p in reversed(island2_control_points[:-1])]
        for i, point in enumerate(island2_control_points):
            self.refpoints[f"island2_control_point_{i}"] = point
        island2_polygon = pya.DPolygon(
            bspline_points(island2_control_points, self.island_spline_samples, startpoint=True, endpoint=True)
        )
        island2_region = pya.Region(island2_polygon.to_itype(self.layout.dbu))
        island2_taper = pya.Region(
            pya.DPolygon(
                [
                    # protrude taper into island in case of precision errors
                    pya.DPoint(self.island2_taper_width / 2, island2_top - taper_height - 1),
                    pya.DPoint(self.island2_taper_width / 2, island2_top - taper_height),
                    pya.DPoint(self.island2_taper_junction_width / 2, island2_top),
                    pya.DPoint(-self.island2_taper_junction_width / 2, island2_top),
                    pya.DPoint(-self.island2_taper_width / 2, island2_top - taper_height),
                    # protrude taper into island in case of precision errors
                    pya.DPoint(-self.island2_taper_width / 2, island2_top - taper_height - 1),
                ]
            ).to_itype(self.layout.dbu)
        )
        return island2_region + island2_taper
