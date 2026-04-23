"""Simulation helpers for the spline-based SCDevice double-pads qubit."""

from kqcircuits.simulations.single_element_simulation import get_single_element_sim_class

from scdevice_pcells.qubits.double_pads_sqnl import DoublePadsSQNL


def get_double_pads_sqnl_sim_class():
    """Return a single-element simulation class for ``DoublePadsSQNL``."""

    return get_single_element_sim_class(DoublePadsSQNL)


DoublePadsSQNLSimulation = get_double_pads_sqnl_sim_class()

__all__ = ["DoublePadsSQNLSimulation", "get_double_pads_sqnl_sim_class"]
