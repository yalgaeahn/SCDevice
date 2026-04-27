"""Custom junction PCells for SCDevice."""

from kqcircuits.junctions import junction_type_choices

SQNL_MANHATTAN_SINGLE_JUNCTION = "Sqnl Manhattan Single Junction"

if SQNL_MANHATTAN_SINGLE_JUNCTION not in junction_type_choices:
    junction_type_choices.append(SQNL_MANHATTAN_SINGLE_JUNCTION)

__all__ = ["SQNL_MANHATTAN_SINGLE_JUNCTION"]
