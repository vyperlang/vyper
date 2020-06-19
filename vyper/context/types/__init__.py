from vyper.context.types import indexable, meta, value
from vyper.context.types.bases import BasePureType
from vyper.context.types.event import Event


def get_pure_types():
    result = {}

    for module in (indexable, value):
        submodules = [
            v
            for v in module.__dict__.values()
            if getattr(v, "__package__", None) == module.__package__
        ]
        for item in submodules:
            result.update(
                (v._id, v)
                for v in item.__dict__.values()
                if isinstance(getattr(v, "_id", None), str) and issubclass(v, BasePureType)
            )

    return result


def get_types():
    result = {"event": Event}
    result.update(meta.META_TYPES)
    result.update(get_pure_types())

    return result
