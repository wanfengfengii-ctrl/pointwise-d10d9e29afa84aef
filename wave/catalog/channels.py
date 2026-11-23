from dataclasses import dataclass
from fractions import Fraction
from wave.catalog.validation import require_identifier, require_unit, require_positive_rate


@dataclass(frozen=True)
class Channel:
    channel_id: str
    unit: str
    input_rate: Fraction

    def __post_init__(self):
        object.__setattr__(self, "channel_id", require_identifier(self.channel_id))
        object.__setattr__(self, "unit", require_unit(self.unit))
        object.__setattr__(self, "input_rate", require_positive_rate(self.input_rate))

    def record(self):
        return {"channel_id": self.channel_id, "unit": self.unit, "input_rate": self.input_rate}


def register_channel(repository, channel_id, unit, input_rate):
    channel = Channel(channel_id, unit, input_rate)
    with repository.transaction():
        try:
            previous = get_channel(repository, channel.channel_id)
        except KeyError:
            repository.insert_channel(channel.channel_id, channel.record())
        else:
            if previous != channel:
                raise ValueError("channel binding conflict")
            return previous
    return channel


def get_channel(repository, channel_id):
    record = repository.load_channel(require_identifier(channel_id))
    return Channel(**record)
