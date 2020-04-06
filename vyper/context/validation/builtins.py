from decimal import (
    Decimal,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions import (
    Literal,
    Reference,
    annotation_declaration,
    builtin_functions,
)
from vyper.context.types import (
    builtins,
    get_builtin_type,
    user_defined,
)
from vyper.context.types.bases.structure import (
    EnvironmentVariableType,
)

BUILTIN_TYPE_MODULES = [
    builtins,
    user_defined,
]
BUILTIN_CONSTANTS = {
    "EMPTY_BYTES32": ("bytes32", vy_ast.Hex, "0x0000000000000000000000000000000000000000000000000000000000000000"),  # NOQA: E501
    "ZERO_ADDRESS": ("address", vy_ast.Hex, "0x0000000000000000000000000000000000000000"),
    "MAX_INT128": ("int128", vy_ast.Int, 2 ** 127 - 1),
    "MIN_INT128": ("int128", vy_ast.Int, -(2 ** 127)),
    "MAX_DECIMAL": ("decimal", vy_ast.Decimal, Decimal(2 ** 127 - 1)),
    "MIN_DECIMAL": ("decimal", vy_ast.Decimal, Decimal(-(2 ** 127))),
    "MAX_UINT256": ("uint256", vy_ast.Int, 2 ** 256 - 1),
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
        "value": "uint256",
    },
    "tx": {"origin": "address"},
    "log": {},
}


def add_builtin_namespace(vyper_ast_node):

    """Adds builtin types and definitions to the namespace."""

    get_types()
    add_environment_variables()
    add_builtin_functions()
    add_builtin_constants(vyper_ast_node)
    # TODO reserved keywords


def _type_filter(value):
    return isinstance(value, type) and isinstance(getattr(value, "_id", None), str)


def get_types():

    type_classes = set()
    for module in BUILTIN_TYPE_MODULES:
        type_classes.update(filter(_type_filter, module.__dict__.values()))

    for obj in type_classes:
        namespace[obj._id] = obj()

    for obj in filter(_type_filter, annotation_declaration.__dict__.values()):
        namespace[obj._id] = obj()


def add_builtin_constants(vyper_ast_node):
    for name, (type_, node, value) in BUILTIN_CONSTANTS.items():
        type_ = get_builtin_type(type_)
        namespace[name] = Literal.from_type(type_, name, value)
        vy_ast.folding.replace_constant(vyper_ast_node, name, node(value=value))


def add_environment_variables():
    for name, values in ENVIRONMENT_VARS.items():
        members = {}
        for k, v in values.items():
            member_type = get_builtin_type(v)
            members[k] = Reference.from_type(member_type, f"{name}.{k}", is_readonly=True)
        typ = EnvironmentVariableType(name, members)
        namespace[name] = Reference.from_type(typ, name, is_readonly=True)

    namespace['self'] = Reference.from_type(get_builtin_type("address"), "self", is_readonly=True)


def add_builtin_functions():

    for obj in filter(_type_filter, builtin_functions.__dict__.values()):
        namespace[obj._id] = obj()
