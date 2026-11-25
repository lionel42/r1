"""Propagation of calibration scales from reference tanks to all tanks.

Python port of the GCwerks R1 programs (``R1calc2``, ``R1diff``,
``R1drift_update`` and ``R1plot``).
"""

from r1.calc import CalcResults, GasResult, calculate
from r1.io.config import R1Config

__all__ = ["CalcResults", "GasResult", "R1Config", "calculate"]
__version__ = "0.1.0"
