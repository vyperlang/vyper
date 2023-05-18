from functools import cached_property
from typing import Dict, List, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABI_GIntM, ABI_Tuple, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    EnumDeclarationException,
    EventDeclarationException,
    InterfaceViolation,
    InvalidAttribute,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
    VariableDeclarationException,
)
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.utils import validate_expected_type, validate_unique_method_ids
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.primitives import AddressT
from vyper.semantics.types.subscriptable import HashMapT
from vyper.semantics.types.utils import type_from_abi, type_from_annotation
from vyper.utils import keccak256


# user defined type
class _UserType(VyperType):
    def __eq__(self, other):
        return self is other

    # TODO: revisit this once user types can be imported via modules
    def compare_type(self, other):
        return super().compare_type(other) and self._id == other._id

    def __hash__(self):
        return hash(id(self))


# note: enum behaves a lot like uint256, or uints in general.
class EnumT(_UserType):
    # this is a carveout because currently we allow dynamic arrays of
    # enums, but not static arrays of enums
    _as_darray = True
    _is_prim_word = True
    _as_hashmap_key = True

    def __init__(self, name: str, members: dict) -> None:
        if len(members.keys()) > 256:
            raise EnumDeclarationException("Enums are limited to 256 members!")

        super().__init__()
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
    def from_EnumDef(cls, base_node: vy_ast.EnumDef) -> "EnumT":
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
        members: Dict = {}

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            raise EnumDeclarationException("Enum must have members", base_node)

        for i, node in enumerate(base_node.body):
            if not isinstance(node, vy_ast.Expr) or not isinstance(node.value, vy_ast.Name):
                raise EnumDeclarationException("Invalid syntax for enum member", node)

            member_name = node.value.id
            if member_name in members:
                raise EnumDeclarationException(
                    f"Enum member '{member_name}' has already been declared", node.value
                )

            members[member_name] = i

        return cls(base_node.name, members)

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[VyperType]:
        # TODO
        return None

    def to_toplevel_abi_dict(self) -> List[Dict]:
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

    def __init__(self, name: str, arguments: dict, indexed: list) -> None:
        super().__init__(members=arguments)
        self.name = name
        self.indexed = indexed
        self.event_id = int(keccak256(self.signature.encode()).hex(), 16)

    # backward compatible
    @property
    def arguments(self):
        return self.members

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.arguments.values())
        return f"event {self.name}({arg_types})"

    # TODO rename to abi_signature
    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments.values())})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "EventT":
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
        indexed: List = [i["indexed"] for i in abi["inputs"]]
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
        members: Dict = {}
        indexed: List = []

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            return EventT(base_node.name, members, indexed)

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

        return cls(base_node.name, members, indexed)

    def _ctor_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, len(self.arguments))
        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

    def to_toplevel_abi_dict(self) -> List[Dict]:
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


class InterfaceT(_UserType):
    _type_members = {"address": AddressT()}
    _is_prim_word = True
    _as_array = True
    _as_hashmap_key = True

    def __init__(self, _id: str, members: dict, events: dict) -> None:
        validate_unique_method_ids(list(members.values()))  # explicit list cast for mypy
        super().__init__(members)

        self._id = _id
        self.events = events

    @property
    def getter_signature(self):
        return (), AddressT()

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()

    def __repr__(self):
        return f"{self._id}"

    # when using the type itself (not an instance) in the call position
    # maybe rename to _ctor_call_return
    def _ctor_call_return(self, node: vy_ast.Call) -> "InterfaceT":
        self._ctor_arg_types(node)

        return self

    def _ctor_arg_types(self, node):
        validate_call_args(node, 1)
        validate_expected_type(node.args[0], AddressT())
        return [AddressT()]

    def _ctor_kwarg_types(self, node):
        return {}

    # TODO x.validate_implements(other)
    def validate_implements(self, node: vy_ast.ImplementsDecl) -> None:
        namespace = get_namespace()
        unimplemented = []

        def _is_function_implemented(fn_name, fn_type):
            vyper_self = namespace["self"].typ
            if name not in vyper_self.members:
                return False
            s = vyper_self.members[name]
            if isinstance(s, ContractFunctionT):
                to_compare = vyper_self.members[name]
            # this is kludgy, rework order of passes in ModuleNodeVisitor
            elif isinstance(s, VarInfo) and s.is_public:
                to_compare = s.decl_node._metadata["func_type"]
            else:
                return False

            return to_compare.implements(fn_type)

        # check for missing functions
        for name, type_ in self.members.items():
            if not isinstance(type_, ContractFunctionT):
                # ex. address
                continue

            if not _is_function_implemented(name, type_):
                unimplemented.append(name)

        # check for missing events
        for name, event in self.events.items():
            if (
                name not in namespace
                or not isinstance(namespace[name], EventT)
                or namespace[name].event_id != event.event_id
            ):
                unimplemented.append(name)

        if len(unimplemented) > 0:
            # TODO: improve the error message for cases where the
            # mismatch is small (like mutability, or just one argument
            # is off, etc).
            missing_str = ", ".join(sorted(unimplemented))
            raise InterfaceViolation(
                f"Contract does not implement all interface functions or events: {missing_str}",
                node,
            )

    def to_toplevel_abi_dict(self) -> List[Dict]:
        abi = []
        for event in self.events.values():
            abi += event.to_toplevel_abi_dict()
        for func in self.functions.values():
            abi += func.to_toplevel_abi_dict()
        return abi

    @property
    def functions(self):
        return {k: v for (k, v) in self.members.items() if isinstance(v, ContractFunctionT)}

    @classmethod
    def from_json_abi(cls, name: str, abi: dict) -> "InterfaceT":
        """
        Generate an `InterfaceT` object from an ABI.

        Arguments
        ---------
        name : str
            The name of the interface
        abi : dict
            Contract ABI

        Returns
        -------
        InterfaceT
            primitive interface type
        """
        members: Dict = {}
        events: Dict = {}

        names = [i["name"] for i in abi if i.get("type") in ("event", "function")]
        collisions = set(i for i in names if names.count(i) > 1)
        if collisions:
            collision_list = ", ".join(sorted(collisions))
            raise NamespaceCollision(
                f"ABI '{name}' has multiple functions or events "
                f"with the same name: {collision_list}"
            )

        for item in [i for i in abi if i.get("type") == "function"]:
            members[item["name"]] = ContractFunctionT.from_abi(item)
        for item in [i for i in abi if i.get("type") == "event"]:
            events[item["name"]] = EventT.from_abi(item)

        return cls(name, members, events)

    # TODO: split me into from_InterfaceDef and from_Module
    @classmethod
    def from_ast(cls, node: Union[vy_ast.InterfaceDef, vy_ast.Module]) -> "InterfaceT":
        """
        Generate an `InterfaceT` object from a Vyper ast node.

        Arguments
        ---------
        node : InterfaceDef | Module
            Vyper ast node defining the interface
        Returns
        -------
        InterfaceT
            primitive interface type
        """
        if isinstance(node, vy_ast.Module):
            members, events = _get_module_definitions(node)
        elif isinstance(node, vy_ast.InterfaceDef):
            members = _get_class_functions(node)
            events = {}
        else:
            raise StructureException("Invalid syntax for interface definition", node)

        return cls(node.name, members, events)


def _get_module_definitions(base_node: vy_ast.Module) -> Tuple[Dict, Dict]:
    functions: Dict = {}
    events: Dict = {}
    for node in base_node.get_children(vy_ast.FunctionDef):
        if "external" in [i.id for i in node.decorator_list if isinstance(i, vy_ast.Name)]:
            func = ContractFunctionT.from_FunctionDef(node)
            functions[node.name] = func
    for node in base_node.get_children(vy_ast.VariableDecl, {"is_public": True}):
        name = node.target.id
        if name in functions:
            raise NamespaceCollision(
                f"Interface contains multiple functions named '{name}'", base_node
            )
        functions[name] = ContractFunctionT.getter_from_VariableDecl(node)
    for node in base_node.get_children(vy_ast.EventDef):
        name = node.name
        if name in functions or name in events:
            raise NamespaceCollision(
                f"Interface contains multiple objects named '{name}'", base_node
            )
        events[name] = EventT.from_EventDef(node)

    return functions, events


def _get_class_functions(base_node: vy_ast.InterfaceDef) -> Dict[str, ContractFunctionT]:
    functions = {}
    for node in base_node.body:
        if not isinstance(node, vy_ast.FunctionDef):
            raise StructureException("Interfaces can only contain function definitions", node)
        if node.name in functions:
            raise NamespaceCollision(
                f"Interface contains multiple functions named '{node.name}'", node
            )
        if len(node.decorator_list) > 0:
            raise StructureException(
                "Function definition in interface cannot be decorated", node.decorator_list[0]
            )
        functions[node.name] = ContractFunctionT.from_FunctionDef(node, is_interface=True)

    return functions


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
    def from_ast_def(cls, base_node: vy_ast.StructDef) -> "StructT":
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
        members: Dict[str, VyperType] = {}
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
                suggestions_str = get_levenshtein_error_suggestions(key.get("id"), members, 1.0)
                raise UnknownAttribute(
                    f"Unknown or duplicate struct member. {suggestions_str}", key or value
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

        return StructT(self._id, self.member_types)
