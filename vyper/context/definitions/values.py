from typing import (
    Optional,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions.bases import (
    BaseDefinition,
    MemberDefinition,
    PublicDefinition,
    ReadOnlyDefinition,
    SequenceDefinition,
    ValueDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
    get_literal_or_raise,
)
from vyper.context.types import (
    UnionType,
    get_type_from_annotation,
)
from vyper.context.types.bases.structure import (
    MemberType,
    ValueType,
)
from vyper.context.utils import (
    compare_types,
    is_subtype,
    validate_call_args,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    TypeMismatch,
)


def build_value_definition(
    name: str, annotation: vy_ast.VyperNode, value: Optional[vy_ast.VyperNode]
):
    """
    Generates a variable definition object from ast nodes.

    Arguments
    ---------
    name : str
        Name of the variable.
    annotation : VyperNode
        Vyper ast node representing the type of the variable.
    value : VyperNode | None
        Vyper ast node representing the initial value of the variable. Can be
        None if the variable has no initial value assigned.

    Returns
    -------
    Variable object.
    """

    is_public = False
    if isinstance(annotation, vy_ast.Call) and annotation.get('func.id') in ("constant", "public"):
        validate_call_args(annotation, 1)
        if annotation.get('func.id') == "constant":
            return _from_constant(name, annotation.args[0], value)
        else:
            is_public = True
            annotation = annotation.args[0]

    if isinstance(annotation, vy_ast.Call):
        key = annotation.get('func.id')
        if isinstance(namespace.get(key), BaseDefinition):
            return namespace[key].from_ann_assign(name, annotation, value, is_public)

    var_type = get_type_from_annotation(annotation)

    if value:
        if isinstance(value, vy_ast.Constant) and isinstance(var_type, ValueType):
            var_type.from_literal(value)
        else:
            value_var = get_definition_from_node(value)
            try:
                compare_types(var_type, value_var.type, value)
            except TypeMismatch as exc:
                if isinstance(value_var, Literal):
                    raise InvalidLiteral(f"Invalid literal type for '{var_type}'", value) from None
                raise exc

    return Reference.from_type(var_type, name, is_public=is_public)


def _from_constant(name, annotation, value):
    var_type = get_type_from_annotation(annotation)

    value = get_literal_or_raise(value)
    compare_types(var_type, value.type, value)

    return Literal.from_type(var_type, name, value.value)


def _build_class(type_name, bases, var_type):
    """
    Private method used for dynamic class generation.

    Literal and Reference classes are created dynamically in order to limit
    their according to the underlying BaseType.

    Accessed via `Literal.from_type` and `Reference.from_type`

    Arguments
    ---------
    type_name : string
        The name of the class to be created.
    bases : Tuple[ValueDefinition, ...]
        tuple of ValueDefinition classes, placed at the top of the new class MRO.
    var_type : BaseType | List
        BaseType object, or list of BaseTypes, that the definition is built around.

    Returns
    -------
    Dynamic ValueDefinition class.
    """
    if isinstance(var_type, (list, tuple)):
        # if var_type includes multiple BaseTypes, definition must allow indexing
        bases += (SequenceDefinition,)
    elif isinstance(var_type, MemberType):
        # if var_type is a MemberType, definition must allow member access
        bases += (MemberDefinition,)

    return type(type_name, bases, {})


class Literal(ReadOnlyDefinition):

    def __init__(self, name, var_type, value=None):
        super().__init__(name or f"{var_type} literal", var_type)
        self.value = value

    @classmethod
    def from_type(cls, var_type, name, value):
        """
        Generates a Literal object from a BaseType.

        Arguments
        ---------
        var_type : BaseType | List
            A BaseType, or list of BaseTypes.
        name : str
            Name for this object. Used in exceptions.
        value : Any
            Literal value of the definition.

        Returns
        -------
        Literal object.
        """
        return _build_class("Literal", (Literal,), var_type)(name, var_type, value)


class Reference(ValueDefinition):
    """
    A reference definition.

    TODO Reference objects represent the assignment of a type (or types) to a name.
    They hold additional information about the assignment, such as whether it is
    a constant or public. They also provide methods for interaction with the
    underlying type.

    Class attributes
    ----------------
    type : _BaseType | list
        The type object represented by this variable. If the variable is an array,
        this will be a list of types.
    value
        The initial value assigned to this variable. Can be a literal value, another
        variable, a list of one or both, or None.
    members : dict
        A dictionary of definitions for members of this variable. Only used if
        the underlying type is a MemberType.
    is_public : bool
        Boolean indicating if the variable is public.
    """

    def __init__(self, name, var_type):
        super().__init__(name, var_type)
        if isinstance(self, PublicDefinition):
            self.is_public = True

    @classmethod
    def from_type(cls, var_type, name, is_readonly=False, is_public=False):
        """
        Generates a Reference object from a BaseType.

        Arguments
        ---------
        var_type : BaseType | List
            A BaseType, or list of BaseTypes.
        name : str
            The name of this reference. Used in exceptions.
        is_readonly : bool
            Boolean indicating if this object is modifiable.
        is_public : bool
            Boolean indicating if this object is public (has an automatically
            generated external getter method)

        Returns
        -------
        Reference object.
        """
        bases = (Reference,)
        if is_readonly:
            bases += (ReadOnlyDefinition,)
        if is_public:
            bases += (PublicDefinition,)
        return _build_class("Reference", bases, var_type)(name, var_type)

    @classmethod
    def from_operation(cls, node):
        """
        Generates a Reference object from an operation or comparison node.

        Arguments
        ---------
        node : UnaryOp, BinOp, BoolOp, Compare
            Vyper ast node.

        Returns
        -------
        Reference
            Reference object representing the outcome of the operation.
        """
        if isinstance(node, vy_ast.UnaryOp):
            type_ = _unary_op(node)
        elif isinstance(node, vy_ast.BinOp):
            type_ = _binop(node)
        elif isinstance(node, vy_ast.BoolOp):
            type_ = _boolean_op(node)
        elif isinstance(node, vy_ast.Compare):
            type_ = _comparator(node)
        else:
            raise CompilerPanic(f"Unexpected node type for from_operation: {type(node).__name__}")
        return cls.from_type(type_, "")

    def get_signature(self):
        # TODO arrays
        return (), self.type


# -x
def _unary_op(node):
    value = get_definition_from_node(node.operand)
    value.type.validate_numeric_op(node)
    return value.type


# x and y, x or y
def _boolean_op(node):
    values = [get_definition_from_node(i) for i in node.values]
    values[0].type.validate_boolean_op(node)
    for item in values[1:]:
        compare_types(values[0].type, item.type, node)

    return namespace['bool']


# x + y
def _binop(node):
    left, right = (get_definition_from_node(i) for i in (node.left, node.right))
    compare_types(left.type, right.type, node)
    left.type.validate_numeric_op(node)
    type_ = left.type
    if isinstance(left.type, UnionType) and len(left.type) == 1:
        type_ = next(iter(type_))
    return type_


# x < y
def _comparator(node):
    left, right = (get_definition_from_node(i) for i in (node.left, node.right))

    if isinstance(node.op, vy_ast.In):
        if not is_subtype(left.type, ValueType) or not isinstance(right.type, list):
            raise InvalidOperation(
                "Can only use 'in' comparator between single type and list", node
            )
        compare_types(left.type, right.type[0], node)
    else:
        if isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq)):
            if hasattr(left.type, 'length') and hasattr(right.type, 'length'):
                # for equality comparisons on types with a length,
                # the longer must be on the lefthand side
                left, right = sorted((left, right), key=lambda k: k.type.length, reverse=True)
        elif isinstance(left.type, (list, tuple)):
            raise InvalidOperation("Sequence types can only be compared via equality", node)
        else:
            left.type.validate_comparator(node)
        compare_types(left.type, right.type, node)

    return namespace['bool']
