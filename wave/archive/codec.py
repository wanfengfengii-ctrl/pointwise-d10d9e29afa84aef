from fractions import Fraction
import json
import math
from wave.catalog.validation import require_rational


def encode_rational(value):
    value = require_rational(value)
    return [value.numerator, value.denominator]


def decode_rational(value):
    return require_rational(value)


def encode_record(value):
    if isinstance(value, Fraction):
        return {"$r": encode_rational(value)}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("record keys must be strings")
        return {key: encode_record(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode_record(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError("record contains unsupported or nonfinite value")


def canonical_json(value):
    return json.dumps(encode_record(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _restore(value):
    if isinstance(value, dict):
        if set(value) == {"$r"}:
            return decode_rational(value["$r"])
        return {key: _restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite stored value")
    return value


def _bad_constant(value):
    raise ValueError("nonfinite JSON number: " + value)


def decode_record(text):
    return _restore(json.loads(text, parse_constant=_bad_constant))
