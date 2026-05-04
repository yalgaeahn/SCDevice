"""Custom junction PCells for SCDevice."""

from kqcircuits.junctions import junction_type_choices

SQNL_DIRECT_LEAD_SIM = "Sqnl Direct Lead Sim"
SQNL_MANHATTAN_SINGLE_JUNCTION_V2 = "Sqnl Manhattan Single Junction V2"
SQNL_MANHATTAN_SINGLE_JUNCTION = SQNL_MANHATTAN_SINGLE_JUNCTION_V2

for junction_type in (SQNL_MANHATTAN_SINGLE_JUNCTION_V2, SQNL_DIRECT_LEAD_SIM):
    if junction_type not in junction_type_choices:
        junction_type_choices.append(junction_type)

__all__ = [
    "SQNL_DIRECT_LEAD_SIM",
    "SQNL_MANHATTAN_SINGLE_JUNCTION",
    "SQNL_MANHATTAN_SINGLE_JUNCTION_V2",
]
