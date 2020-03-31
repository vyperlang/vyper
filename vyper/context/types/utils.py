from typing import (
    Dict,
    List,
    Set,
    Tuple,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types import (
    builtins,
)
from vyper.context.types.union import (
    UnionType,
)
from vyper.exceptions import (
    InvalidType,
    OverflowException,
)


def check_numeric_bounds(type_str: str, node: vy_ast.Num) -> bool:
    """
    Validates that a Num node's value is within the bounds of a given type.

    Arguments
    ---------
    type_str : str
        String representation of the type, e.g. "int128"
    node : Num
        Vyper ast node to validate

    Returns
    -------
    None. Raises an exception if the check fails.
    """
    size = int(type_str.strip("uint") or 256)
    if size < 8 or size > 256 or size % 8:
        raise InvalidType(f"Invalid type: {type_str}")
    if type_str.startswith("u"):
        lower, upper = 0, 2 ** size - 1
    else:
        lower, upper = -(2 ** (size - 1)), 2 ** (size - 1) - 1

    value = node.value
    if value < lower:
        raise OverflowException(f"Value is below lower bound for given type ({lower})", node)
    if value > upper:
        raise OverflowException(f"Value exceeds upper bound for given type ({upper})", node)


def get_builtin_type(type_definition: Union[List, Set, Dict, Tuple, str]):
    """
    Given a type definition, returns a type object or list of type objects.

    Arguments
    ---------
    type_definition : str | tuple | list
        str - The name of a single type to be returned.
        dict - An ABI type definition.
        set - A union type.
        tuple - The first value is the type name, the remaining values are passed
                as arguments when initializing the type class.
        list - Each item should be a string or tuple defining a single type.
    """
    if isinstance(type_definition, list):
        return [get_builtin_type(i) for i in type_definition]

    if isinstance(type_definition, set):
        return UnionType(get_builtin_type(i) for i in type_definition)

    if isinstance(type_definition, dict):
        type_definition = type_definition['type']
        if type_definition == "fixed168x10":
            type_definition = "decimal"
    if isinstance(type_definition, tuple):
        name, args = type_definition[0], type_definition[1:]
    else:
        name, args = type_definition, ()

    value = builtins.__dict__.values()
    type_class = next(v for v in value if getattr(v, '_id', None) == name)

    return type_class(*args)
