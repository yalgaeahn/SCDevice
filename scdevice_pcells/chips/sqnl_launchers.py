from kqcircuits.chips.chip import Chip
from kqcircuits.defaults import default_sampleholders
from kqcircuits.util.parameters import Param, pdt

sampleholder_type_choices = list(default_sampleholders.keys())


class SqnlLaunchers(Chip):
    """Chip PCell with predefined SQNL launchers."""

    sampleholder_type = Param(pdt.TypeString, "Type of the launchers", "SMA8", choices=sampleholder_type_choices)

    def build(self):
        self.name_mask = "M001"
        self.name_chip = "BASIC"
        self.name_copy = "KAIST"
        self.name_brand = "SQNL"
        self.produce_launchers(self.sampleholder_type)
