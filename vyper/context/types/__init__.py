from vyper.context.types import indexable, meta, value
from vyper.context.types.bases import BasePrimitive


def get_primitive_types():
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
                if isinstance(getattr(v, "_id", None), str) and issubclass(v, BasePrimitive)
            )

    return result


def get_types():
    result = {}
    result.update(meta.META_TYPES)
    result.update(get_primitive_types())

    return result
