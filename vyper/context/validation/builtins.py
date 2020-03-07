from decimal import (
    Decimal,
)

from vyper.context import (
    namespace,
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
TYPE_ALIASES = {
    "timedelta": ("uint256", "sec"),
    "timestamp": ("uint256", "sec"),
    "wei_value": ("uint256", "wei"),
}
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
    "msg": {  # TODO block msg.sender and msg.value in private methods
        "gas": "uint256",
        "sender": "address",
        "value": ("uint256", "wei"),
    },
    "tx": {"origin": "address"},
    "log": {},
}


def generate_builtin_namespace():

    """Adds builtin types and definitions to the namespace."""

    get_types()
    add_builtin_units()
    add_type_aliases()
    add_builtin_constants()
    add_environment_variables()
    add_builtin_functions()
    # TODO reserved keywords


def _type_filter(value):
    return type(value) is type and isinstance(getattr(value, "_id", None), str)


def get_types():

    type_classes = set()
    for module in BUILTIN_TYPE_MODULES:
        type_classes.update(filter(_type_filter, module.__dict__.values()))

    for obj in type_classes:
        namespace[obj._id] = obj()


def add_builtin_units():
    namespace.update({unit.name: unit for unit in BUILTIN_UNITS})


def add_type_aliases():
    for name, typ in TYPE_ALIASES.items():
        namespace[name] = get_builtin_type(typ)


def add_builtin_constants():
    for name, (value, typ) in BUILTIN_CONSTANTS.items():
        typ = get_builtin_type(typ)
        namespace[name] = Variable(name, typ, value, True)


def add_environment_variables():
    for name, values in ENVIRONMENT_VARS.items():
        members = {}
        for k, v in values.items():
            members[k] = get_builtin_type(v)
        typ = bases.EnvironmentVariableType(name, members)
        namespace[name] = Variable(name, typ, None, True)

    namespace['self'] = Variable("self", get_builtin_type("address"), None, True)


def add_builtin_functions():

    for obj in filter(_type_filter, builtin_functions.__dict__.values()):
        namespace[obj._id] = obj()
