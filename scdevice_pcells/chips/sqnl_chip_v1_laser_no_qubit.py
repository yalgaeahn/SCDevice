"""SQNL chip v1 laser-writer layout without qubit pads or junctions."""

from scdevice_pcells.chips.sqnl_chip_v1 import SqnlSingle
from scdevice_pcells.qubits.double_pads_sqnl_laser_coupler import (
    DoublePadsSQNLLaserCoupler,
)


class SqnlSingleLaserNoQubit(SqnlSingle):
    """SQNL chip v1 with only the qubit coupler footprint for laser writing."""

    def _produce_qubits(self):
        qubit = self.add_element(DoublePadsSQNLLaserCoupler)
        qubit_spacing_y = 2600
        qubits_center_x = 5e3 + 400
        y_a = float(self.feedline_y) + qubit_spacing_y / 2
        qb0_refpoints = self._produce_qubit(qubit, qubits_center_x, y_a, 2, "qb_0")
        return (qb0_refpoints,)
