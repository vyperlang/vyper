
from vyper.context.datatypes import (
    metatypes,
    types as vy_types,
)
from vyper.context.datatypes.units import (
    Unit,
)

BUILTIN_UNITS = [
    Unit(name="sec", description="number of seconds", enclosing_scope="builtin"),
    Unit(name="wei", description="amount of Ether in wei", enclosing_scope="builtin"),
]


def _type_filter(value):
    return type(value) is type and isinstance(getattr(value, '_id', None), str)


def get_meta_types(namespace):
    for obj in filter(_type_filter, vy_types.__dict__.values()):
        key = obj._id
        namespace[key] = metatypes.BuiltinMetaType(namespace, obj)

    for obj in filter(_type_filter, metatypes.__dict__.values()):
        key = obj._id
        namespace[key] = obj(namespace)

    return namespace


def add_builtin_units(namespace):
    namespace.update({unit.name: unit for unit in BUILTIN_UNITS})
    return namespace
