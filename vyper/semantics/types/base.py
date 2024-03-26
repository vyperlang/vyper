from functools import cached_property
from typing import Any, Dict, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABIType
from vyper.ast.identifiers import validate_identifier
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
)
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.data_locations import DataLocation


# Some fake type with an overridden `compare_type` which accepts any RHS
# type of type `type_`
class _GenericTypeAcceptor:
    def __repr__(self):
        return f"GenericTypeAcceptor({self.type_})"

    def __init__(self, type_):
        self.type_ = type_

    def compare_type(self, other):
        if isinstance(other, self.type_):
            return True
        # compare two GenericTypeAcceptors -- they are the same if the base
        # type is the same
        return isinstance(other, self.__class__) and other.type_ == self.type_

    def to_dict(self):
        # this shouldn't really appear in the AST type annotations, but it's
        # there for certain string literals which don't have a known type. this
        # should be fixed soon by improving type inference. for now just put
        # *something* in the AST.
        return {"generic": self.type_.typeclass}


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
    _supports_external_calls: bool, optional
        Whether or not this type supports external calls. Currently
        limited to `InterfaceT`s
    _attribute_in_annotation: bool, optional
        Whether or not this type can be attributed in a type
        annotation, like IFoo.SomeType. Currently limited to
        `InterfaceT`s.
    """

    typeclass: str = None  # type: ignore

    _id: str  # rename to `_name`
    _type_members: Optional[Dict] = None
    _valid_literal: Tuple = ()
    _invalid_locations: Tuple = ()
    _is_prim_word: bool = False
    _equality_attrs: Optional[Tuple] = None
    _is_array_type: bool = False
    _is_bytestring: bool = False  # is it a bytes or a string?

    _as_array: bool = False  # rename to something like can_be_array_member
    _as_hashmap_key: bool = False

    _supports_external_calls: bool = False
    _attribute_in_annotation: bool = False

    size_in_bytes = 32  # default; override for larger types

    decl_node: Optional[vy_ast.VyperNode] = None

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
        if self is other:
            return True
        return (
            type(self) is type(other) and self._get_equality_attrs() == other._get_equality_attrs()
        )

    def __lt__(self, other):
        return self.abi_type.selector_name() < other.abi_type.selector_name()

    # return a dict suitable for serializing in the AST
    def to_dict(self):
        ret = {"name": self._id}
        if self.decl_node is not None:
            ret["type_decl_node"] = self.decl_node.get_id_dict()
        if self.typeclass is not None:
            ret["typeclass"] = self.typeclass

        # use dict ctor to block duplicates
        return dict(**self._addl_dict_fields(), **ret)

    # for most types, this is a reasonable implementation, but it can
    # be overridden as needed.
    def _addl_dict_fields(self):
        keys = self._equality_attrs or ()
        ret = {}
        for k in keys:
            if k.startswith("_"):
                continue
            v = getattr(self, k)
            if hasattr(v, "to_dict"):
                v = v.to_dict()
            ret[k] = v
        return ret

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

    def get_size_in(self, location: DataLocation):
        if location in (DataLocation.STORAGE, DataLocation.TRANSIENT):
            return self.storage_size_in_words
        if location == DataLocation.MEMORY:
            return self.memory_bytes_required
        if location == DataLocation.CODE:
            return self.memory_bytes_required

        raise CompilerPanic("unreachable: invalid location {location}")  # pragma: nocover

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
        raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node.op)

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
        raise StructureException(f"{self} is not callable", node)

    @classmethod
    def get_subscripted_type(self, node: vy_ast.VyperNode) -> None:
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

    def _check_add_member(self, name):
        if (prev_type := self.members.get(name)) is not None:
            msg = f"Member '{name}' already exists in {self}"
            raise NamespaceCollision(msg, prev_decl=prev_type.decl_node)

    def add_member(self, name: str, type_: "VyperType") -> None:
        validate_identifier(name)
        self._check_add_member(name)
        self.members[name] = type_

    def get_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        if key in self.members:
            return self.members[key]

        # special error message for types with no members
        if not self.members:
            raise StructureException(f"{self} instance does not have members", node)

        hint = get_levenshtein_error_suggestions(key, self.members, 0.3)
        raise UnknownAttribute(f"{self} has no member '{key}'.", node, hint=hint)

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


class _VoidType(VyperType):
    _id = "(void)"


# sentinel for function calls which return nothing
VOID_TYPE = _VoidType()


def map_void(typ: Optional[VyperType]) -> VyperType:
    if typ is None:
        return VOID_TYPE
    return typ


# A type type. Used internally for types which can live in expression
# position, ex. constructors (events, interfaces and structs), and also
# certain builtins which take types as parameters
class TYPE_T(VyperType):
    def __init__(self, typedef):
        super().__init__()

        self.typedef = typedef

    def to_dict(self):
        return {"type_t": self.typedef.to_dict()}

    def __repr__(self):
        return f"type({self.typedef})"

    def check_modifiability_for_call(self, node, modifiability):
        if hasattr(self.typedef, "_ctor_modifiability_for_call"):
            return self.typedef._ctor_modifiability_for_call(node, modifiability)
        raise StructureException("Value is not callable", node)

    # dispatch into ctor if it's called
    def fetch_call_return(self, node):
        if hasattr(self.typedef, "_ctor_call_return"):
            return self.typedef._ctor_call_return(node)
        raise StructureException("Value is not callable", node)

    def infer_arg_types(self, node, expected_return_typ=None):
        if hasattr(self.typedef, "_ctor_arg_types"):
            return self.typedef._ctor_arg_types(node)
        raise StructureException("Value is not callable", node)

    def infer_kwarg_types(self, node):
        if hasattr(self.typedef, "_ctor_kwarg_types"):
            return self.typedef._ctor_kwarg_types(node)
        raise StructureException("Value is not callable", node)

    # dispatch into get_type_member if it's dereferenced, ex.
    # MyFlag.FOO
    def get_member(self, key, node):
        if hasattr(self.typedef, "get_type_member"):
            return self.typedef.get_type_member(key, node)
        raise UnknownAttribute("Value is not attributable", node)


def is_type_t(x: VyperType, t: type) -> bool:
    return isinstance(x, TYPE_T) and isinstance(x.typedef, t)
