from typing import Dict, Optional

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.indexable.sequence import ArrayDefinition
from vyper.context.validation.utils import (
    get_exact_type_from_node,
    get_index_value,
    validate_expected_type,
)
from vyper.exceptions import (
    ConstancyViolation,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
    VariableDeclarationException,
    VyperException,
)


def get_type_from_abi(abi_type: Dict, is_constant: bool = False, is_public: bool = False):
    """
    Return a type object from an ABI type definition.

    Arguments
    ---------
    abi_type : Dict
       A type definition taken from the `input` or `output` field of an ABI.

    Returns
    -------
    BasePureType
        Pure type object.
    """
    type_string = abi_type["type"]
    if type_string == "fixed168x10":
        type_string = "decimal"

    namespace = get_namespace()
    try:
        return namespace[type_string]._type(is_constant=is_constant, is_public=is_public)
    except KeyError:
        raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def get_type_from_annotation(
    node: vy_ast.VyperNode, is_constant: bool = False, is_public: bool = False
):
    """
    Return a type object for the given AST node.

    Arguments
    ---------
    node : VyperNode
        Vyper ast node from the `annotation` member of an `AnnAssign` node.

    Returns
    -------
    BasePureType
        Pure type object.
    """
    namespace = get_namespace()
    try:
        # get id of leftmost `Name` node from the annotation
        type_name = next(i.id for i in node.get_descendants(vy_ast.Name, include_self=True))
        type_obj = namespace[type_name]
    except StopIteration:
        raise StructureException("Invalid syntax for type declaration", node)
    except UndeclaredDefinition:
        raise UnknownType("Not a valid type - value is undeclared", node) from None

    if getattr(type_obj, "_as_array", False) and isinstance(node, vy_ast.Subscript):
        # if type can be an array and node is a subscript, create an `ArrayDefinition`
        try:
            length = get_index_value(node.slice)
        except VyperException as exc:
            raise UnknownType(str(exc)) from None
        value_type = get_type_from_annotation(node.value, is_constant, False)
        return ArrayDefinition(value_type, length, is_constant, is_public)

    try:
        return type_obj.from_annotation(node, is_constant, is_public)
    except AttributeError:
        raise UnknownType(f"'{type_name}' is not a valid type", node) from None


def _check_literal(node):
    # check whether a given node is a literal value
    if isinstance(node, vy_ast.Constant):
        return True
    elif isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        for item in node.elements:
            if not _check_literal(item):
                return False
        return True
    else:
        return False


def _check_constant(node):
    # check whether a given node is a literal value or constant variable
    if _check_literal(node):
        return True
    if isinstance(node, (vy_ast.Tuple, vy_ast.List)):
        for item in node.elements:
            if not _check_constant(item):
                return False
        return True

    value_type = get_exact_type_from_node(node)
    return getattr(value_type, "is_constant", False)


def build_type_from_ann_assign(
    annotation: vy_ast.VyperNode, value: Optional[vy_ast.VyperNode], is_constant=False,
):
    """
    Generate a new `BaseType` object from the given nodes.

    Arguments
    ---------
    annotation : VyperNode
        Vyper ast node representing the type of the variable.
    value : VyperNode | None
        Vyper ast node representing the initial value of the variable. Can be
        None if the variable has no initial value assigned.
    is_constant : bool, optional
        Boolean indicating if the value is read-only.

    Returns
    -------
    BaseType
        Type object.
    """
    is_public = False
    if isinstance(annotation, vy_ast.Call):
        # the annotation is a function call, e.g. `foo: constant(uint256)`
        call_name = annotation.get("func.id")
        if call_name in ("constant", "public"):
            validate_call_args(annotation, 1)
            if call_name == "constant":
                # declaring a constant
                is_constant = True
                if not value:
                    raise VariableDeclarationException(
                        "Constant must be declared with a value", annotation
                    )
                if not _check_literal(value):
                    raise ConstancyViolation("Value must be a literal", value)
            elif call_name == "public":
                # declaring a public variable
                is_public = True
            # remove the outer call node, to handle cases such as `public(map(..))`
            annotation = annotation.args[0]

    var_type = get_type_from_annotation(annotation, is_constant, is_public)
    if is_constant and value and not _check_constant(value):
        raise ConstancyViolation("Value must be a literal or environment variable", value)

    if value is not None:
        validate_expected_type(value, var_type)

    return var_type
