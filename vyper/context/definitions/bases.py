from collections import (
    OrderedDict,
)
from typing import (
    Optional,
    Tuple,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    definitions,
)
from vyper.context.types import (
    ValueType,
    get_builtin_type,
)
from vyper.context.utils import (
    compare_types,
    validate_call_args,
)
from vyper.exceptions import (
    ArrayIndexException,
    CompilerPanic,
    ConstancyViolation,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    TypeMismatch,
    UnknownAttribute,
    VyperException,
)


class BaseDefinition:
    """
    Inherited class common to all classes representing definitions.

    This class is never directly invoked. It is inherited by all definition classes.

    Object attributes
    ----------------
    name : str
       Name of the definition, used for error reporting. For variables this should
       be the assigned name, for literals and other un-named references it should
       attempt to give an accurate explanation of "what" the definition represents.
    """
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    def get_member(self, node: Union[vy_ast.Attribute, vy_ast.FunctionDef]) -> "BaseDefinition":
        """
        Get a member of this definition.

        Implemented in `MemberDefinition`.
        """
        raise StructureException(f"{type(self).__name__} does not support members", node)

    def get_index(self, node):
        """
        Get a definition object for an element within this sequence.

        Implemented in `SequenceDefinition`.
        """
        raise StructureException(f"{type(self).__name__} does not support indexing", node.slice)

    def get_signature(self):
        """
        Return the input and output types for a definition.

        Implemented by classes which can inherit from `PublicDefinition`.
        """
        raise StructureException(f"{type(self).__name__} has no signature")

    def fetch_call_return(self, node):
        """
        Validate a call to this function and return the result.

        Implemented in `CallableDefinition`.
        """
        raise StructureException(f"{type(self).__name__} is not callable", node)

    def validate_clear(self, node):
        """
        Validate a `clear()` action on the definition.

        Implemented in `ValueDefinition`.
        """
        raise InvalidOperation(f"{type(self).__name__} cannot be cleared", node)

    def validate_modification(self, node, op=None):
        """
        Validate a modification to the assigned value of this definition.

        Implemented in `ValueDefinition`.
        """
        raise ConstancyViolation(f"{type(self).__name__} is not modifiable", node)


class PublicDefinition(BaseDefinition):
    """
    Inherited class for definitions which have the capacity to be public.

    Public definitions accessible via an external function call. For variables
    this means a getter function is automatically generated.

    Object attributes
    ----------------
     is_public : bool
        Boolean indicating if the function is public.
    """
    def get_signature(self):
        """
        Return the input and output types for a definition.

        This method must be implemented in classes which may inherit `PublicDefinition`.

        Returns
        -------
        tuple
            A sequence of type objects representing the inputs arguments used to
            call this definition externally.
        BaseType | None
            A type object representing the the return value(s) when calling this
            definition externally. May be None if the definition does not return
            anything.
        """
        raise CompilerPanic(f"{type(self)} has not implemented get_signature")

    def _compare_signature(self, other: "PublicDefinition") -> bool:
        """
        Compares the signature of this definition with another definition.

        Used when determining if an interface has been implemented. This method
        should not be directly implemented by any inherited classes.
        """
        arguments, return_type = self.get_signature()

        if not (  # NOQA: E721
            self.is_public and
            self.name == other.name and
            len(arguments) == len(other.arguments) and
            type(return_type) is type(other.return_type)
        ):
            return False

        try:
            if arguments:
                other_args = other.arguments
                if isinstance(other_args, dict):
                    other_args = [i.type for i in other_args.values()]
                compare_types(arguments, other_args, None)
            if return_type:
                compare_types(return_type, other.return_type, None)
        except VyperException:
            return False

        return True


class ValueDefinition(BaseDefinition):
    """
    Base class for definitions representing a value.

    This class is never instantiated directly. Value definitions are created
    through `Reference.from_type` or `Literal.from_type`.

    Object Attributes
    -----------------
    type : BaseType | list
        A vyper type object, or list of type objects, represented by this
        definition. If `type` is a list, the class should also inherit
        `SequenceDefinition`.
    """
    def __init__(self, name, var_type):
        super().__init__(name)
        assert not isinstance(var_type, BaseDefinition)
        self.type = var_type

    def _type_str(self, type_=None):
        """
        Get a human-readable string for the type.
        """
        if type_ is None:
            type_ = self.type
        if not isinstance(type_, list):
            return str(type_)
        return f"{self._type_str(type_[0])}[{len(type_)}]"

    def validate_modification(self, node, op=None):
        """
        Validate a modification to the assigned value of this definition.

        This method is called against the target definition when validating
        `Assign` and `AugAssign` nodes.

        Arguments
        ---------
        node : VypeNode
            Node representing the value side of an assignment.
        op : VyperNode, optional
            Node representing the operand being applied, if the assignment
            is via `AugAssign`.
        """
        if hasattr(node, 'op'):
            self.type.validate_numeric_op(node)

        value = definitions.get_definition_from_node(node.value)
        try:
            compare_types(self.type, value.type, node.value)
        except TypeMismatch as exc:
            if isinstance(value, definitions.Literal):
                raise InvalidLiteral(
                    f"Invalid literal type for {self._type_str()}", node.value
                ) from None
            raise exc
        except VyperException as exc:
            raise exc.with_annotation(node.value)

    def validate_clear(self, node: vy_ast.VyperNode) -> None:
        """
        Validate a `clear()` action on the definition.

        Arguments
        ---------
        node : VyperNode
            Vyper node referencing this definition within the `clear` call

        Returns
        -------
        None. Raises an exception if the value cannot be cleared.
        """
        pass

    def fetch_call_return(self, node):
        raise StructureException(f"{self._type_str()} type is not callable", node)

    def get_member(self, node):
        raise StructureException(f"{self._type_str()} type does not support members", node)

    def get_index(self, node):
        raise StructureException(f"{self._type_str()} type does not support indexing", node.slice)


class ReadOnlyDefinition(ValueDefinition):
    """
    Base class for value definitions which are not modifiable.

    Modifications are prevented by bypassing immediate parents in calls to
    `validate_modification` and directly calling to `BaseDefinition`, which raises.

    `isinstance(v, ReadOnlyDefinition)` should be used for constancy checks on
    value definitions.
    """
    def validate_modification(self, node, op=None):
        """
        Validate a modification to the assigned value of this definition.

        Always raises by calling to `BaseDefinition.validate_modification`.
        """
        return BaseDefinition.validate_modification(self, node, op)

    def validate_clear(self, node):
        """
        Validate a `clear()` action on the definition.

        Always raises by calling to `BaseDefinition.validate_clear`.
        """
        return BaseDefinition.validate_clear(self, node)


class SequenceDefinition(ValueDefinition):
    """
    Base class for value definitions that allow indexed access: `value[index]`

    The `type` member of a sequence definition must be a list or tuple. The
    length of `type` determines the length of the definition.
    """
    def get_index(self, node: vy_ast.Subscript) -> ValueDefinition:
        """
        Get a definition object for an element within this sequence.

        Arguments
        ---------
        node : Subscript
            Node representing the reference to the definition index.

        Returns
        -------
            BaseDefinition
        """
        value = definitions.get_definition_from_node(node.slice.value)
        compare_types(value.type, get_builtin_type({'int128', 'uint256'}), node)
        if hasattr(value, 'value'):
            if value.value >= len(self.type):
                raise ArrayIndexException("Array index out of range", node)
            if value.value < 0:
                raise ArrayIndexException("Array index cannot use negative integers", node)
            var_type = self.type[value.value]
            if hasattr(self, 'value'):
                value = self.value[value.value]
                return type(self)("", var_type, value)
        else:
            var_type = self.type[0]
        return definitions.Reference.from_type(var_type, f"{self}[{value}]")


class MemberDefinition(ValueDefinition):
    """
    Base class for value definitions that allow member access: `value.member`

    The `type` member of a member definition must be `MemberType`. Members may
    be "type members" (common across all definitions of the same type) or
    "definition members" (unique to a single definition).

    Class attributes
    ----------------
    members : dict
        A dictionary of definitions representing members of this definitions.
    """
    def __init__(self, name: str, var_type):
        super().__init__(name, var_type)
        self.members = {}

    def add_member(self, attr: str, value: ValueDefinition) -> None:
        """
        Add a new definition member.

        For adding a type member, use `MemberType.add_type_members`.

        Arguments
        ---------
        attr : str
            The name of the member.
        value : ValueDefinition
            Definition object to be added.
        """
        assert isinstance(value, BaseDefinition)
        try:
            self._get_member(attr)
        except UnknownAttribute:
            self.members[attr] = value
        else:
            raise NamespaceCollision(attr)

    def get_member(self, node: Union[vy_ast.Attribute, vy_ast.FunctionDef]) -> BaseDefinition:
        """
        Get a member of this definition.

        If a member with the given name exists in both the definition and the
        type, the definition member returned.

        Arguments
        ---------
        node : Attribute | FunctionDef
            Node representing the attribute to be accessed.

        Returns
        -------
            BaseDefinition
        """
        try:
            if isinstance(node, vy_ast.FunctionDef):
                return self._get_member(node.name)
            elif isinstance(node, vy_ast.Attribute):
                return self._get_member(node.attr)
        except VyperException as exc:
            raise exc.with_annotation(node)

        raise CompilerPanic(f"Unexpected node: {type(node)}")

    def _get_member(self, key):
        if key in self.members:
            return self.members[key]

        return self.type.get_type_member(key)

    def validate_clear(self, node):
        """
        Validate a `clear()` action on the definition.

        Raises if any definition members or type members cannot be cleared.
        """
        try:
            for value in self.members.values():
                value.validate_clear(node)
            for value in self.type.members.values():
                value.validate_clear(node)
        except VyperException:
            raise InvalidOperation(f"Cannot clear {self} member '{value}'", node)


class CallableDefinition(BaseDefinition):
    """
    Base class for callable definitions.

    Object attributes
    -----------------
    arguments : OrderedDict
        A dictionary of values representing arguments when calling the function.
        The values may be either type objects or Variables.
    arg_count : int | tuple
        The number of required positional arguments when calling the function.
        If given as a tuple, the values correspond to the minimum and maximum
        number of required arguments.
    kwarg_keys : list
        A list of optional keyword arguments when calling the function. Automatically
        generated by comparing the number of values in arguments with the minimum
        value from arg_count.
    return_type : BaseType | tuple, optional
        The type(s) to be returned upon successfully calling this function.
    """
    def __init__(
        self,
        name: str,
        arguments: OrderedDict,
        arg_count: Union[Tuple[int, int], int],
        return_type,
    ):
        BaseDefinition.__init__(self, name)
        self.arguments = arguments
        self.arg_count = arg_count
        self.return_type = return_type
        self.kwarg_keys = []
        if isinstance(arg_count, tuple):
            self.kwarg_keys = list(self.arguments)[self.arg_count[0]:]

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[ValueDefinition]:
        """
        Validate a call to this function and return the result.

        If the given arguments are invalid, `fetch_call_return` must always raise.

        This method performs validation on the number and type of call arguments,
        and generates a value definition based on `return_type`. Inheriting classes
        should subclass or replace this method to perform additional checks or
        handle logic around effects of calling the definition.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to validate.

        Returns
        -------
        BaseDefinition, optional
            Definition object(s) generated as a result of the call.
        """
        validate_call_args(node, self.arg_count, self.kwarg_keys)
        for arg, key in zip(node.args, self.arguments):
            self._compare_argument(key, arg)
        for kwarg in node.keywords:
            self._compare_argument(kwarg.arg, kwarg.value)
        return definitions.Reference.from_type(self.return_type, "return value")

    def _compare_argument(self, key: str, arg_node: vy_ast.VyperNode):
        """
        Internal helper method for comparing a given argument against the expected
        one during a call to this definition.

        Arguments
        ---------
        key : str
            Name of the argument.
        arg_node : VyperNode
            Vyper node representing the given argument value when performing
            the call.
        """
        given = definitions.get_definition_from_node(arg_node)
        if isinstance(self.arguments[key], ValueDefinition):
            expected_type = self.arguments[key].type
        else:
            expected_type = self.arguments[key]

        if isinstance(arg_node, vy_ast.Constant) and isinstance(expected_type, ValueType):
            expected_type.from_literal(arg_node)
        else:
            compare_types(expected_type, given.type, arg_node)
