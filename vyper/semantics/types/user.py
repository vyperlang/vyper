from functools import cached_property
from typing import Optional

from vyper import ast as vy_ast
from vyper.abi_types import ABI_GIntM, ABI_Tuple, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    EventDeclarationException,
    FlagDeclarationException,
    InvalidAttribute,
    NamespaceCollision,
    StructureException,
    UnfoldableNode,
    UnknownAttribute,
    VariableDeclarationException,
)
from vyper.semantics.analysis.base import Modifiability
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.utils import check_modifiability, validate_expected_type
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.subscriptable import HashMapT
from vyper.semantics.types.utils import type_from_abi, type_from_annotation
from vyper.utils import keccak256


# user defined type
class _UserType(VyperType):
    def __init__(self, members=None):
        super().__init__(members=members)

    def __eq__(self, other):
        return self is other

    def compare_type(self, other):
        # object exact comparison is a bit tricky here since we have
        # to be careful to construct any given user type exactly
        # only one time. however, the alternative requires reasoning
        # about both the name and source (module or json abi) of
        # the type.
        return self is other

    def __hash__(self):
        return hash(id(self))


# note: enum behaves a lot like uint256, or uints in general.
class FlagT(_UserType):
    # this is a carveout because currently we allow dynamic arrays of
    # enums, but not static arrays of enums
    _as_darray = True
    _is_prim_word = True
    _as_hashmap_key = True

    def __init__(self, name: str, members: dict) -> None:
        if len(members.keys()) > 256:
            raise FlagDeclarationException("Enums are limited to 256 members!")

        super().__init__(members=None)

        self._id = name

        self._enum_members = members

        # use a VyperType for convenient access to the `get_member` function
        # also conveniently checks well-formedness of the members namespace
        self._helper = VyperType(members)

        # set the name for exception handling in `get_member`
        self._helper._id = name

    def get_type_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        self._helper.get_member(key, node)
        return self

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self._enum_members)
        return f"enum {self.name}({arg_types})"

    @property
    def abi_type(self):
        # note: not compatible with solidity enums - those have
        # ABI type uint8.
        return ABI_GIntM(m_bits=256, signed=False)

    @property
    def name(self):
        return f"{self._id}"

    def validate_numeric_op(self, node):
        allowed_ops = (vy_ast.BitOr, vy_ast.BitAnd, vy_ast.Invert, vy_ast.BitXor)
        if isinstance(node.op, allowed_ops):
            return
        # fallback to parent class error message
        super().validate_numeric_op(node)

    def validate_comparator(self, node):
        if isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq, vy_ast.In, vy_ast.NotIn)):
            return
        # fallback to parent class error message
        super().validate_comparator(node)

    # @property
    # def signature(self):
    #    return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments)})"

    @classmethod
    def from_FlagDef(cls, base_node: vy_ast.FlagDef) -> "FlagT":
        """
        Generate an `Enum` object from a Vyper ast node.

        Arguments
        ---------
        base_node : EnumDef
            Vyper ast node defining the enum
        Returns
        -------
        Enum
        """
        members: dict = {}

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            raise FlagDeclarationException("Enum must have members", base_node)

        for i, node in enumerate(base_node.body):
            if not isinstance(node, vy_ast.Expr) or not isinstance(node.value, vy_ast.Name):
                raise FlagDeclarationException("Invalid syntax for enum member", node)

            member_name = node.value.id
            if member_name in members:
                raise FlagDeclarationException(
                    f"Enum member '{member_name}' has already been declared", node.value
                )

            members[member_name] = i

        return cls(base_node.name, members)

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[VyperType]:
        # TODO
        return None

    def to_toplevel_abi_dict(self) -> list[dict]:
        # TODO
        return []


class EventT(_UserType):
    """
    Event type.

    Attributes
    ----------
    arguments : dict
        Event arguments.
    event_id : int
        Keccak of the event signature, converted to an integer. Used as the
        first topic when the event is emitted.
    indexed : list
        A list of booleans indicating if each argument within the event is
        indexed.
    name : str
        Name of the event.
    """

    _invalid_locations = tuple(iter(DataLocation))  # not instantiable in any location

    def __init__(
        self,
        name: str,
        arguments: dict,
        indexed: list,
        decl_node: Optional[vy_ast.VyperNode] = None,
    ) -> None:
        super().__init__(members=arguments)
        self.name = name
        self.indexed = indexed
        assert len(self.indexed) == len(self.arguments)
        self.event_id = int(keccak256(self.signature.encode()).hex(), 16)

        self.decl_node = decl_node

    # backward compatible
    @property
    def arguments(self):
        return self.members

    def __repr__(self):
        args = []
        for is_indexed, (_, argtype) in zip(self.indexed, self.arguments.items()):
            argtype_str = repr(argtype)
            if is_indexed:
                argtype_str = f"indexed({argtype_str})"
            args.append(f"{argtype_str}")
        return f"event {self.name}({','.join(args)})"

    # TODO rename to abi_signature
    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments.values())})"

    @classmethod
    def from_abi(cls, abi: dict) -> "EventT":
        """
        Generate an `Event` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing an event.

        Returns
        -------
        Event object.
        """
        members: dict = {}
        indexed: list = [i["indexed"] for i in abi["inputs"]]
        for item in abi["inputs"]:
            members[item["name"]] = type_from_abi(item)
        return cls(abi["name"], members, indexed)

    @classmethod
    def from_EventDef(cls, base_node: vy_ast.EventDef) -> "EventT":
        """
        Generate an `Event` object from a Vyper ast node.

        Arguments
        ---------
        base_node : EventDef
            Vyper ast node defining the event
        Returns
        -------
        Event
        """
        members: dict = {}
        indexed: list = []

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            return cls(base_node.name, members, indexed, base_node)

        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Events can only contain variable definitions", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during event declaration", node)
            if not isinstance(node.target, vy_ast.Name):
                raise StructureException("Invalid syntax for event member name", node.target)
            member_name = node.target.id
            if member_name in members:
                raise NamespaceCollision(
                    f"Event member '{member_name}' has already been declared", node.target
                )

            annotation = node.annotation
            if isinstance(annotation, vy_ast.Call) and annotation.get("func.id") == "indexed":
                validate_call_args(annotation, 1)
                if indexed.count(True) == 3:
                    raise EventDeclarationException(
                        "Event cannot have more than three indexed arguments", annotation
                    )
                indexed.append(True)
                annotation = annotation.args[0]
            else:
                indexed.append(False)

            members[member_name] = type_from_annotation(annotation)

        return cls(base_node.name, members, indexed, base_node)

    def _ctor_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, len(self.arguments))
        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

    def to_toplevel_abi_dict(self) -> list[dict]:
        return [
            {
                "name": self.name,
                "inputs": [
                    dict(**typ.to_abi_arg(name=k), **{"indexed": idx})
                    for (k, typ), idx in zip(self.arguments.items(), self.indexed)
                ],
                "anonymous": False,
                "type": "event",
            }
        ]


class StructT(_UserType):
    _as_array = True

    def __init__(self, _id, members, ast_def=None):
        super().__init__(members)

        self._id = _id

        self.ast_def = ast_def

    @cached_property
    def name(self) -> str:
        # Alias for API compatibility with codegen
        return self._id

    # duplicated code in TupleT
    def tuple_members(self):
        return [v for (_k, v) in self.tuple_items()]

    # duplicated code in TupleT
    def tuple_keys(self):
        return [k for (k, _v) in self.tuple_items()]

    def tuple_items(self):
        return list(self.members.items())

    @cached_property
    def member_types(self):
        """
        Alias to match TupleT API without shadowing `members` on TupleT
        """
        return self.members

    @classmethod
    def from_StructDef(cls, base_node: vy_ast.StructDef) -> "StructT":
        """
        Generate a `StructT` object from a Vyper ast node.

        Arguments
        ---------
        node : StructDef
            Vyper ast node defining the struct
        Returns
        -------
        StructT
            Struct type
        """

        struct_name = base_node.name
        members: dict[str, VyperType] = {}
        for node in base_node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException(
                    "Struct declarations can only contain variable definitions", node
                )
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            if not isinstance(node.target, vy_ast.Name):
                raise StructureException("Invalid syntax for struct member name", node.target)
            member_name = node.target.id

            if member_name in members:
                raise NamespaceCollision(
                    f"struct member '{member_name}' has already been declared", node.value
                )

            members[member_name] = type_from_annotation(node.annotation)

        return cls(struct_name, members, ast_def=base_node)

    def __repr__(self):
        return f"{self._id} declaration object"

    def _try_fold(self, node):
        if len(node.args) != 1:
            raise UnfoldableNode("wrong number of args", node.args)
        args = [arg.get_folded_value() for arg in node.args]
        if not isinstance(args[0], vy_ast.Dict):
            raise UnfoldableNode("not a dict")

        # it can't be reduced, but this lets upstream code know it's constant
        return node

    @property
    def size_in_bytes(self):
        return sum(i.size_in_bytes for i in self.member_types.values())

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self.member_types.values()])

    def to_abi_arg(self, name: str = "") -> dict:
        components = [t.to_abi_arg(name=k) for k, t in self.member_types.items()]
        return {"name": name, "type": "tuple", "components": components}

    # TODO breaking change: use kwargs instead of dict
    # when using the type itself (not an instance) in the call position
    # maybe rename to _ctor_call_return
    def _ctor_call_return(self, node: vy_ast.Call) -> "StructT":
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise VariableDeclarationException(
                "Struct values must be declared via dictionary", node.args[0]
            )
        if next((i for i in self.member_types.values() if isinstance(i, HashMapT)), False):
            raise VariableDeclarationException(
                "Struct contains a mapping and so cannot be declared as a literal", node
            )

        members = self.member_types.copy()
        keys = list(self.member_types.keys())
        for i, (key, value) in enumerate(zip(node.args[0].keys, node.args[0].values)):
            if key is None or key.get("id") not in members:
                hint = get_levenshtein_error_suggestions(key.get("id"), members, 1.0)
                raise UnknownAttribute(
                    "Unknown or duplicate struct member.", key or value, hint=hint
                )
            expected_key = keys[i]
            if key.id != expected_key:
                raise InvalidAttribute(
                    "Struct keys are required to be in order, but got "
                    f"`{key.id}` instead of `{expected_key}`. (Reminder: the "
                    f"keys in this struct are {list(self.member_types.items())})",
                    key,
                )

            validate_expected_type(value, members.pop(key.id))

        if members:
            raise VariableDeclarationException(
                f"Struct declaration does not define all fields: {', '.join(list(members))}", node
            )

        return self

    def _ctor_modifiability_for_call(self, node: vy_ast.Call, modifiability: Modifiability) -> bool:
        return all(check_modifiability(v, modifiability) for v in node.args[0].values)
