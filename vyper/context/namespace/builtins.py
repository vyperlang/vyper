from collections import (
    OrderedDict,
)
from decimal import (
    Decimal,
)

from vyper.context.definitions import (
    BuiltinFunction,
    Variable,
)
from vyper.context.types import (
    bases,
    builtins,
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
    Unit(name="sec", description="number of seconds", enclosing_scope="builtin"),
    Unit(name="wei", description="amount of Ether in wei", enclosing_scope="builtin"),
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


def _get_type(namespace, types):
    if isinstance(types, list):
        return [_get_type(namespace, i) for i in types]
    if isinstance(types, tuple):
        return type(namespace[types[0]])(namespace, types[1])
    return type(namespace[types])(namespace)


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
        typ = _get_type(namespace, typ)
        namespace[name] = Variable(namespace, name, "builtin", typ, value, True)


def add_environment_variables(namespace):
    for name, values in ENVIRONMENT_VARS.items():
        members = {}
        for k, v in values.items():
            members[k] = _get_type(namespace, v)
        typ = bases.EnvironmentVariableType(namespace, name, members)
        namespace[name] = Variable(namespace, name, "builtin", typ, None, True)

    namespace['self'] = Variable(
        namespace, "self", "module", type(namespace["address"])(namespace), None, True
    )


# convert
# clear, as_wei_value, as_unitless_number, slice, concat, keccack256
# sha256, method_id, extract32, RLPList, raw_call, raw_log

# assert, raise

BUILTIN_FUNCTIONS = {
    "floor": {
        "input": [("value", "decimal")],
        "return": "int128"
    },
    "ceil": {
        "input": [("value", "decimal")],
        "return": "int128"
    },
    "len": {
        "input": [("b", "bytes")],
        "return": "int128"
    },
    "uint256_addmod": {
        "input": [("a", "uint256"), ("b", "uint256"), ("c", "uint256")],
        "return": "uint256",
    },
    "uint256_mulmod": {
        "input": [("a", "uint256"), ("b", "uint256"), ("c", "uint256")],
        "return": "uint256",
    },
    "sqrt": {
        "input": [("d", "decimal")],
        "return": "decimal",
    },
    "ecrecover": {
        "input": [("hash", "bytes32"), ("v", "uint256"), ("r", "uint256"), ("s", "uint256")],
        "return": "address",
    },
    "ecadd": {
        "input": [("a", ["uint256", "uint256"]), ("b", ["uint256", "uint256"])],
        "return": ["uint256", "uint256"]
    },
    "ecmul": {
        "input": [("point", ["uint256", "uint256"]), ("scalar", "uint256")],
        "return": ["uint256", "uint256"]
    },
    "send": {
        "input": [("to", "address"), ("value", ("uint256", "wei"))],
        "return": None,
    },
    "selfdestruct": {
        "input": [("to", "address")],
        "return": None,
    },
    "assert_modifiable": {
        "input": [("cond", "bool")],
        "return": None,
    },
    "create_forwarder_to": {
        "input": [("target", "address"), ("value", ("uint256", "wei"))],
        "return": "address",
    },
    "blockhash": {
        "input": [("block_num", "uint256")],
        "return": "bytes32",
    }

}


def add_builtin_functions(namespace):
    for name, args in BUILTIN_FUNCTIONS.items():
        arguments = OrderedDict()
        for n, types in args['input']:
            arguments[n] = _get_type(namespace, types)
        return_type = _get_type(namespace, args['return']) if args['return'] else None
        namespace[name] = BuiltinFunction(namespace, name, arguments, len(arguments), return_type)
