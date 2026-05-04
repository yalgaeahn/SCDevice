"""Simulation junction with surrogate pads for direct DoublePadsSQNL attachment."""

from kqcircuits.junctions.junction import Junction
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

DIRECT_LEAD_ATTACH_SPAN_UM = 7.428
SURROGATE_PAD_WIDTH_UM = 8.0
SURROGATE_PAD_LENGTH_UM = 2.0


class SqnlDirectLeadSim(Junction):
    """Simulation-only junction that replaces physical leads with simple metal pads."""

    attach_span = Param(
        pdt.TypeDouble,
        "Distance between direct upper/lower junction attach points.",
        DIRECT_LEAD_ATTACH_SPAN_UM,
        unit="um",
    )
    surrogate_pad_width = Param(
        pdt.TypeDouble,
        "Width of the simulation-only metal surrogate pads.",
        SURROGATE_PAD_WIDTH_UM,
        unit="um",
    )
    surrogate_pad_length = Param(
        pdt.TypeDouble,
        "Length of each simulation-only metal surrogate pad.",
        SURROGATE_PAD_LENGTH_UM,
        unit="um",
    )
    include_background_gap = Param(
        pdt.TypeBoolean, "Add base metal gap around the surrogate pads.", True
    )

    def build(self):
        if self.attach_span <= 0:
            raise ValueError("Direct lead simulation attach span must be positive.")
        if self.surrogate_pad_width <= 0:
            raise ValueError("Surrogate pad width must be positive.")
        if self.surrogate_pad_length <= 0:
            raise ValueError("Surrogate pad length must be positive.")
        if 2 * self.surrogate_pad_length >= self.attach_span:
            raise ValueError(
                "Surrogate pad lengths must leave a positive junction port gap."
            )

        lower = pya.DPoint(0, 0)
        upper = pya.DPoint(0, self.attach_span)
        lower_inner = pya.DPoint(0, self.surrogate_pad_length)
        upper_inner = pya.DPoint(0, self.attach_span - self.surrogate_pad_length)

        half_width = self.surrogate_pad_width / 2
        lower_pad = pya.DBox(
            -half_width,
            0,
            half_width,
            self.surrogate_pad_length,
        )
        upper_pad = pya.DBox(
            -half_width,
            self.attach_span - self.surrogate_pad_length,
            half_width,
            self.attach_span,
        )
        self.cell.shapes(self.get_layer("base_metal_addition")).insert(lower_pad)
        self.cell.shapes(self.get_layer("base_metal_addition")).insert(upper_pad)

        clearance = pya.DBox(
            -half_width - self.margin,
            -self.margin,
            half_width + self.margin,
            self.attach_span + self.margin,
        )
        self.add_protection(clearance)
        if self.include_background_gap:
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(
                pya.DBox(
                    -half_width - self.margin,
                    0,
                    half_width + self.margin,
                    self.attach_span,
                )
            )

        self.refpoints["attach_island_1"] = upper
        self.refpoints["attach_island_2"] = lower
        self.refpoints["origin_squid"] = lower
        self.refpoints["port_common"] = upper
        self.refpoints["port_squid_a"] = upper_inner
        self.refpoints["port_squid_b"] = lower_inner
