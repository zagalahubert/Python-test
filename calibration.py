"""Pure calibration: coefficients and measurements in, new values out.

No function here opens a file, reads configuration, prints, or configures logging.
The coefficients correct values within one unit; this is not unit conversion.
"""
from math import isfinite


def calibrate_value(value: float, scale: float = 1.0, offset: float = 0.0) -> float:
    """Apply y = scale * x + offset using supplied, not fitted, coefficients."""
    result = scale * value + offset
    if not isfinite(result):
        raise ValueError("Calibration produced a non-finite value.")
    return result


def calibrate_reading(reading: dict, scale: float, offset: float) -> dict:
    """SOLUTION C1: copy a record and change only the copy's numerical value."""
    # A shallow copy is sufficient: our record fields are strings and numbers.
    corrected = reading.copy()
    corrected["value"] = calibrate_value(reading["value"], scale, offset)
    # Identity, time and unit survive; the raw dictionary is never modified.
    return corrected
