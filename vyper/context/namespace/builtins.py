
from vyper.context.datatypes import (
    builtins,
    user_defined,
)
from vyper.context.datatypes.units import (
    Unit,
)

BUILTIN_TYPE_MODULES = [
    builtins,
    user_defined,
]
BUILTIN_UNITS = [
    Unit(name="sec", description="number of seconds", enclosing_scope="builtin"),
    Unit(name="wei", description="amount of Ether in wei", enclosing_scope="builtin"),
]


def _type_filter(value):
    return type(value) is type and isinstance(getattr(value, '_id', None), str)


def get_types(namespace):

    type_classes = set()
    for module in BUILTIN_TYPE_MODULES:
        type_classes.update(filter(_type_filter, module.__dict__.values()))

    for obj in type_classes:
        namespace[obj._id] = obj(namespace)

    return namespace


def add_builtin_units(namespace):
    namespace.update({unit.name: unit for unit in BUILTIN_UNITS})
    return namespace
