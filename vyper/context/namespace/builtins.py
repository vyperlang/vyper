from decimal import (
    Decimal,
)

from vyper.context.definitions import (
    Variable,
    builtin_functions,
)
from vyper.context.types import (
    bases,
    builtins,
    get_builtin_type,
    user_defined,
)
from vyper.context.types.units import (
    Unit,
)

BUILTIN_TYPE_MODULES = [
    builtins,
    user_defined,
]
BUILTIN_UNITS = [
    Unit(name="sec", description="number of seconds"),
    Unit(name="wei", description="amount of Ether in wei"),
]
BUILTIN_CONSTANTS = {
    "EMPTY_BYTES32": ("0x0000000000000000000000000000000000000000000000000000000000000000", "bytes32"),  # NOQA: E501
    "ZERO_ADDRESS": ("0x0000000000000000000000000000000000000000", "address"),
    "MAX_INT128": (2 ** 127 - 1, "int128"),
    "MIN_INT128": (-(2 ** 127) - 1, "int128"),
    "MAX_DECIMAL": (Decimal(2 ** 127 - 1), "decimal"),
    "MIN_DECIMAL": (Decimal(-(2 ** 127)), "decimal"),
    "MAX_UINT256": (2 ** 256 - 1, "uint256"),
    "ZERO_WEI": (0, ("uint256", "wei")),
}
ENVIRONMENT_VARS = {
    "block": {
        "coinbase": "address",
        "difficulty": "uint256",
        "number": "uint256",
        "prevhash": "bytes32",
        "timestamp": "uint256",
    },
    "chain": {"id": "uint256"},
    "msg": {
        "gas": "uint256",
        "sender": "address",
        "value": ("uint256", "wei"),
    },
    "tx": {"origin": "address"},
    "log": {},
}


def _type_filter(value):
    return type(value) is type and isinstance(getattr(value, "_id", None), str)


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
    for name, (value, typ) in BUILTIN_CONSTANTS.items():
        typ = get_builtin_type(namespace, typ)
        namespace[name] = Variable(namespace, name, typ, value, True)


def add_environment_variables(namespace):
    for name, values in ENVIRONMENT_VARS.items():
        members = {}
        for k, v in values.items():
            members[k] = get_builtin_type(namespace, v)
        typ = bases.EnvironmentVariableType(namespace, name, members)
        namespace[name] = Variable(namespace, name, typ, None, True)

    namespace['self'] = Variable(
        namespace, "self", type(namespace["address"])(namespace), None, True
    )


def add_builtin_functions(namespace):

    for obj in filter(_type_filter, builtin_functions.__dict__.values()):
        namespace[obj._id] = obj(namespace)
