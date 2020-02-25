from decimal import (
    Decimal,
)
from vyper.context.datatypes import (
    builtins,
    user_defined,
)
from vyper.context.datatypes.units import (
    Unit,
)
from vyper.context.variables import (
    Variable,
)

BUILTIN_TYPE_MODULES = [
    builtins,
    user_defined,
]
BUILTIN_UNITS = [
    Unit(name="sec", description="number of seconds", enclosing_scope="builtin"),
    Unit(name="wei", description="amount of Ether in wei", enclosing_scope="builtin"),
]

BUILTIN_CONSTANTS = {
    'EMPTY_BYTES32': ("0x0000000000000000000000000000000000000000000000000000000000000000", 'bytes32', None),  # NOQA: E501
    'ZERO_ADDRESS': ("0x0000000000000000000000000000000000000000", 'address', None),
    'MAX_INT128': (2**127 - 1, 'int128', None),
    'MIN_INT128': (-2**127 - 1, 'int128', None),
    'MAX_DECIMAL': (Decimal(2**127 - 1), 'decimal', None),
    'MIN_DECIMAL': (Decimal(-2**127), 'decimal', None),
    'MAX_UINT256': (2**256 - 1, 'uint256', None),
    'ZERO_WEI': (0, 'uint256', "wei"),
}


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


def add_builtin_constants(namespace):
    for name, (value, typ, unit) in BUILTIN_CONSTANTS.items():
        typ = type(namespace[typ])(namespace)
        if unit:
            typ.unit = namespace[unit]
        namespace[name] = Variable(namespace, name, "builtin", typ, value, True)
