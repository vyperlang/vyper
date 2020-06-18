from typing import Any, Tuple, Type, Union

from vyper import ast as vy_ast
from vyper.exceptions import (
    CompilerPanic,
    ConstancyViolation,
    InvalidLiteral,
    InvalidOperation,
    StructureException,
)


class BasePureType:
    """
    Base class for pure type classes.

    Pure types are objects that are invoked when casting a variable as a type.
    They must contain a `from_annotation` (and optionally `from_literal`) method
    that returns their equivalent `BaseType` object.

    Attributes
    ----------
    _id : str
        The name of the type.
    _type : BaseType
        The related `BaseType` class generated from this pure type.
    _as_array: bool, optional
        If `True`, this type can be used as the base member for an array.
    _valid_literal : Tuple
        A tuple of Vyper ast classes that may be cast as this type.
    """

    _type: Type["BaseType"]
    _valid_literal: Tuple

    @classmethod
    def from_annotation(
        cls, node: vy_ast.Name, is_constant: bool = False, is_public: bool = False
    ) -> "BaseType":
        """
        Generate a `BaseType` instance of this type from `AnnAssign.annotation`

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the `annotation` member of an `AnnAssign` node.

        Returns
        -------
        BaseType
            BaseType related to the pure type that the method was called on.
        """
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        return cls._type(is_constant, is_public)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> "BaseType":
        """
        Generate a `BaseType` instance of this type from a literal constant.

        This method is called on every pure type class in order to determine
        potential types for a `Constant` AST node.

        Methods that can be cast from literals should include a `_valid_literal`
        attribute, containing a list of AST node classes that may be cast
        as this type. If this attribute is not included, the type cannot be
        cast as a literal.

        Arguments
        ---------
        node : VyperNode
            `Constant` Vyper ast node, or a list or tuple of constants.

        Returns
        -------
        BaseType
            BaseType related to the pure type that the method was called on.
        """
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, cls._valid_literal):
            raise InvalidLiteral(f"Invalid literal type for {cls.__name__}", node)
        return cls._type()

    @classmethod
    def compare_type(cls, other: Union["BaseType", "BasePureType", "AbstractDataType"]) -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by methods in `vyper.context.validation.utils`

        Arguments
        ---------
        other : BaseType
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, cls._type)

    @classmethod
    def fetch_call_return(self, node: vy_ast.Call) -> "BaseType":
        """
        Validate a call to this type and return the result.

        This method must raise if the type is not callable, or the call arguments
        are not valid.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to validate.

        Returns
        -------
        BaseType, optional
            Type generated as a result of the call.
        """
        raise StructureException("Type is not callable", node)

    @classmethod
    def get_index_type(self, node: vy_ast.Index) -> None:
        # always raises - do not implement in inherited classes
        raise StructureException("Types cannot be indexed", node)

    @classmethod
    def get_member(cls, key: str, node: vy_ast.Attribute) -> None:
        # always raises - do not implement in inherited classes
        raise StructureException("Types do not have members", node)

    @classmethod
    def validate_modification(cls, node: Union[vy_ast.Assign, vy_ast.AugAssign]) -> None:
        # always raises - do not implement in inherited classes
        raise InvalidOperation("Cannot assign to a type", node)


class BaseType:
    """
    Base class for casted type classes.

    Casted types are objects that represent the type of a specific object within
    a contract. They are typically derived from a `BasePureType` counterpart.

    Class Attributes
    -----------------
    _id : str
        The name of the type.
    _is_callable : bool, optional
        If `True`, attempts to assign this value without calling it will raise
        a more expressive error message recommending that the user performs a
        function call.

    Object Attributes
    -----------------
    is_constant : bool, optional
        If `True`, the value of this object cannot be modified after assignment.
    """

    def __init__(self, is_constant: bool = False, is_public: bool = False) -> None:
        self.is_constant = is_constant
        self.is_public = is_public

    def from_annotation(cls, node: vy_ast.VyperNode, **kwargs: Any) -> None:
        # always raises, user should have used a pure type
        raise StructureException("Value is not a type", node)

    def compare_type(self, other: Union["BaseType", BasePureType, "AbstractDataType"]) -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by methods in `vyper.context.validation.utils`

        Arguments
        ---------
        other : BaseType
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, type(self))

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]) -> None:
        """
        Validate a numeric operation for this type.

        Arguments
        ---------
        node : UnaryOp | BinOp
            Vyper ast node of the numeric operation to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

    def validate_boolean_op(self, node: vy_ast.BoolOp) -> None:
        """
        Validate a boolean operation for this type.

        Arguments
        ---------
        node : BoolOp
            Vyper ast node of the boolean operation to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise InvalidOperation(f"Invalid type for operand: {self}", node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        """
        Validate a comparator for this type.

        Arguments
        ---------
        node : Compare
            Vyper ast node of the comparator to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        if not isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq)):
            raise InvalidOperation(
                f"Cannot perform {node.op.description} comparison on {self}", node
            )

    def validate_implements(self, node: vy_ast.AnnAssign) -> None:
        """
        Validate an implements statement.

        This method is unique to user-defined interfaces. It should not be
        included in other types.

        Arguments
        ---------
        node : AnnAssign
            Vyper ast node of the implements statement being validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise StructureException("Value is not an interface", node)

    def fetch_call_return(self, node: vy_ast.Call) -> Union["BaseType", None]:
        """
        Validate a call to this value and return the result.

        This method must raise if the value is not callable, or the call arguments
        are not valid.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to validate.

        Returns
        -------
        BaseType, optional
            Type generated as a result of the call.
        """
        raise StructureException("Value is not callable", node)

    def get_index_type(self, node: vy_ast.Index) -> "BaseType":
        """
        Validate an index reference and return the given type at the index.

        Arguments
        ---------
        node : Index
            Vyper ast node from the `slice` member of a Subscript node.

        Returns
        -------
        BaseType
            Type object for value at the given index.
        """
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def get_member(self, key: str, node: vy_ast.Attribute) -> "BaseType":
        """
        Validate an attribute reference and return the given type for the member.

        Arguments
        ---------
        key : str
            Name of the member being accessed.
        node: Attribute
            Vyper ast Attribute node representing the member being accessed.

        Returns
        -------
        BaseType
            A type object for the value of the given member. Raises if the member
            does not exist for the given type.
        """
        raise StructureException(f"Type '{self}' does not support members", node)

    def validate_modification(self, node: Union[vy_ast.Assign, vy_ast.AugAssign]) -> None:
        """
        Validate an attempt to modify this value.

        Raises if the value is a constant or involves an invalid operation.

        Arguments
        ---------
        node : Assign | AugAssign
            Vyper ast node of the modifying action.
        """
        if getattr(self, "is_constant", False):
            # TODO store location information to make this exception more meaningful
            raise ConstancyViolation("Constant value cannot be written to", node)
        if hasattr(node, "op"):
            self.validate_numeric_op(node)

    def compare_signature(self, other: "BaseType") -> bool:
        """
        Compare the signature of this type with another type.

        Used when determining if an interface has been implemented. This method
        should not be directly implemented by any inherited classes.
        """

        if not self.is_public:
            return False

        arguments, return_type = self.get_signature()
        other_arguments, other_return_type = other.get_signature()

        if len(arguments) != len(other_arguments):
            return False
        for a, b in zip(arguments, other_arguments):
            if not a.compare_type(b):
                return False
        if return_type and not return_type.compare_type(other.return_type):
            return False

        return True


class AbstractDataType:
    """
    Base class for abstract type classes.

    Abstract type classes are uncastable, inherited types used for comparison.
    For example, a function that accepts either `int128` or `uint256` might
    perform this comparison using the `IntegerBase` abstract type.
    """

    def compare_type(self, other) -> bool:
        try:
            return super().compare_type(other)
        except AttributeError:
            pass
        return isinstance(other, type(self))
