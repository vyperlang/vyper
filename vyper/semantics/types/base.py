from functools import cached_property
from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABIType
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
)
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.namespace import validate_identifier


# Some fake type with an overridden `compare_type` which accepts any RHS
# type of type `type_`
class _GenericTypeAcceptor:
    def __repr__(self):
        return repr(self.type_)

    def __init__(self, type_):
        self.type_ = type_

    def compare_type(self, other):
        return isinstance(other, self.type_)


class VyperType:
    """
    Base class for vyper types.

    Attributes
    ----------
    _id : str
        The name of the type.
    _as_array: bool, optional
        If `True`, this type can be used as the base member for an array.
    _valid_literal : Tuple
        A tuple of Vyper ast classes that may be assigned this type.
    _invalid_locations : Tuple
        A tuple of invalid `DataLocation`s for this type
    _is_prim_word: bool, optional
        This is a word type like uint256, int8, bytesM or address
    """

    _id: str
    _type_members: Optional[Dict] = None
    _valid_literal: Tuple = ()
    _invalid_locations: Tuple = ()
    _is_prim_word: bool = False
    _equality_attrs: Optional[Tuple] = None
    _is_array_type: bool = False
    _is_bytestring: bool = False  # is it a bytes or a string?

    _as_array: bool = False  # rename to something like can_be_array_member
    _as_hashmap_key: bool = False

    size_in_bytes = 32  # default; override for larger types

    def __init__(self, members: Optional[Dict] = None) -> None:
        self.members: Dict = {}

        # add members that are on the class instance.
        if self._type_members is not None:
            for k, v in self._type_members.items():
                # for builtin members like `contract.address` -- skip namespace
                # validation, as it introduces a dependency cycle
                self.add_member(k, v)

        members = members or {}
        for k, v in members.items():
            self.add_member(k, v)

    def _get_equality_attrs(self):
        return tuple(getattr(self, attr) for attr in self._equality_attrs)

    def __hash__(self):
        return hash(self._get_equality_attrs())

    def __eq__(self, other):
        return (
            type(self) == type(other) and self._get_equality_attrs() == other._get_equality_attrs()
        )

    def __lt__(self, other):
        return self.abi_type.selector_name() < other.abi_type.selector_name()

    @cached_property
    def _as_darray(self):
        return self._as_array

    @property
    def getter_signature(self):
        return (), self

    # TODO not sure if this is a great idea.
    @classmethod
    def any(cls):
        return _GenericTypeAcceptor(cls)

    @property
    def abi_type(self) -> ABIType:
        """
        The ABI type corresponding to this type
        """
        raise CompilerPanic("Method must be implemented by the inherited class")

    @property
    def memory_bytes_required(self) -> int:
        # alias for API compatibility with codegen
        return self.size_in_bytes

    @property
    def storage_size_in_words(self) -> int:
        # consider renaming if other word-addressable address spaces are
        # added to EVM or exist in other arches
        """
        Returns the number of words required to allocate in storage for
        this type
        """
        r = self.memory_bytes_required
        if r % 32 != 0:
            raise CompilerPanic("Memory bytes must be multiple of 32")
        return r // 32

    @property
    def canonical_abi_type(self) -> str:
        """
        The canonical name of this type. Used for ABI types and generating function signatures.
        """
        return self.abi_type.selector_name()

    def to_abi_arg(self, name: str = "") -> Dict[str, Any]:
        """
        The JSON ABI description of this type. Note for complex types,
        the implementation is overridden to be compliant with the spec:
        https://docs.soliditylang.org/en/v0.8.14/abi-spec.html#json
        > An object with members name, type and potentially components
          describes a typed variable. The canonical type is determined
          until a tuple type is reached and the string description up to
          that point is stored in type prefix with the word tuple, i.e.
          it will be tuple followed by a sequence of [] and [k] with
          integers k. The components of the tuple are then stored in the
          member components, which is of array type and has the same
          structure as the top-level object except that indexed is not
          allowed there.
        """
        return {"name": name, "type": self.canonical_abi_type}

    # convenience method for erroring out of invalid ast ops
    def _raise_invalid_op(
        self,
        # TODO maybe make these AST classes inherit from "HasOperator"
        node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign, vy_ast.Compare, vy_ast.BoolOp],
    ) -> None:
        raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

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
            self._raise_invalid_op(node)

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        """
        Validate a numeric operation for this type.

        Arguments
        ---------
        node : UnaryOp | BinOp | AugAssign
            Vyper ast node of the numeric operation to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        self._raise_invalid_op(node)

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
        self._raise_invalid_op(node)

    def validate_literal(self, node: vy_ast.Constant) -> None:
        """
        Validate that a literal node can be annotated with this type

        Arguments
        ---------
        node : VyperNode
            `Constant` Vyper ast node, or a list or tuple of constants.
        """
        if not isinstance(node, self._valid_literal) or not isinstance(node, vy_ast.Constant):
            # should not reach here, by paths into validate_literal.
            raise InvalidLiteral(f"Invalid literal for {self._id}", node)

    def validate_index_type(self, node: vy_ast.Subscript) -> None:
        raise StructureException(f"Not an indexable type: '{self}'", node)

    def compare_type(self, other: "VyperType") -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method does *not* test for type equality, it is a type
        checker function, it should have the meaning: "an expr of type
        <other> can be assigned to an expr of type <self>."

        Arguments
        ---------
        other: VyperType
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, type(self))

    def fetch_call_return(self, node: vy_ast.Call) -> Optional["VyperType"]:
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
        VyperType, optional
            Type generated as a result of the call.
        """
        raise StructureException("Value is not callable", node)

    @classmethod
    def get_subscripted_type(self, node: vy_ast.Index) -> None:
        """
        Return the type of a subscript expression, e.g. x[1]

        Arguments
        ---------
        node: Index
            Vyper ast node from the `slice` member of a Subscript node

        Returns
        -------
        VyperType
            Type object for value at the given index.
        """
        raise StructureException(f"'{self}' cannot be indexed into", node)

    def add_member(self, name: str, type_: "VyperType") -> None:
        validate_identifier(name)
        if name in self.members:
            raise NamespaceCollision(f"Member '{name}' already exists in {self}")
        self.members[name] = type_

    def get_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        if key in self.members:
            return self.members[key]

        # special error message for types with no members
        if not self.members:
            raise StructureException(f"{self} instance does not have members", node)

        suggestions_str = get_levenshtein_error_suggestions(key, self.members, 0.3)
        raise UnknownAttribute(f"{self} has no member '{key}'. {suggestions_str}", node)

    def __repr__(self):
        return self._id


class KwargSettings:
    # convenience class which holds metadata about how to process kwargs.
    # contains the `default` value for the kwarg as a python value, and a
    # flag `require_literal`, which, when True, indicates that the kwarg
    # must be set to a compile-time constant at any call site.
    # (note that the kwarg processing machinery will return a
    # Python value instead of an AST or IRnode in this case).
    def __init__(self, typ, default, require_literal=False):
        self.typ = typ
        self.default = default
        self.require_literal = require_literal


# A type type. Used internally for types which can live in expression
# position, ex. constructors (events, interfaces and structs), and also
# certain builtins which take types as parameters
class TYPE_T:
    def __init__(self, typedef):
        self.typedef = typedef

    def __repr__(self):
        return f"type({self.typedef})"

    # dispatch into ctor if it's called
    def fetch_call_return(self, node):
        if hasattr(self.typedef, "_ctor_call_return"):
            return self.typedef._ctor_call_return(node)
        raise StructureException("Value is not callable", node)

    def infer_arg_types(self, node):
        if hasattr(self.typedef, "_ctor_arg_types"):
            return self.typedef._ctor_arg_types(node)
        raise StructureException("Value is not callable", node)

    def infer_kwarg_types(self, node):
        if hasattr(self.typedef, "_ctor_kwarg_types"):
            return self.typedef._ctor_kwarg_types(node)
        raise StructureException("Value is not callable", node)

    # dispatch into get_type_member if it's dereferenced, ex.
    # MyEnum.FOO
    def get_member(self, key, node):
        if hasattr(self.typedef, "get_type_member"):
            return self.typedef.get_type_member(key, node)
        raise UnknownAttribute("Value is not attributable", node)


def is_type_t(x: VyperType, t: type) -> bool:
    return isinstance(x, TYPE_T) and isinstance(x.typedef, t)
