from fractions import Fraction
import math


def require_identifier(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("identifier must be a nonempty trimmed string")
    return value


def require_unit(value):
    return require_identifier(value)


def require_rational(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a rational")
    if isinstance(value, (int, Fraction)):
        return Fraction(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        numerator, denominator = value
        if (type(numerator) is not int or type(denominator) is not int
                or denominator == 0):
            raise ValueError("rational requires integer numerator and nonzero denominator")
        return Fraction(numerator, denominator)
    raise ValueError("use an integer, Fraction, or [numerator, denominator]")


def require_positive_rate(value):
    result = require_rational(value)
    if result <= 0:
        raise ValueError("rate must be positive")
    return result


def require_index(value):
    if type(value) is not int or value < 0:
        raise ValueError("position must be a nonnegative integer")
    return value


def require_finite_sample(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Fraction)):
        raise ValueError("sample must be a finite real number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError("sample outside finite range") from error
    if not math.isfinite(result):
        raise ValueError("sample must be finite")
    return result
