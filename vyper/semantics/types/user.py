from typing import Dict, List

from vyper import ast as vy_ast
from vyper.abi_types import ABI_GIntM
from vyper.exceptions import (
    EnumDeclarationException,
    StructureException,
    UnimplementedException,
    UnknownAttribute,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation, MemberTypeDefinition, ValueTypeDefinition
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions


class EnumDefinition(MemberTypeDefinition, ValueTypeDefinition):
    def __init__(
        self,
        name: str,
        members: dict,
        location: DataLocation = DataLocation.MEMORY,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        self._id = name
        super().__init__(location, is_constant, is_public, is_immutable)
        for key, val in members.items():
            self.add_member(key, val)

    @property
    def abi_type(self):
        # note: not compatible with solidity enums - those have
        # ABI type uint8.
        return ABI_GIntM(m_bits=256, signed=False)

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


class EnumPrimitive:
    """
    Enum type.

    Attributes
    ----------
    arguments : list of strings
    name : str
        Name of the element.
    """

    def __init__(self, name: str, members: dict) -> None:
        for key in members.keys():
            validate_identifier(key)
        self.name = name
        if len(members.keys()) > 256:
            raise EnumDeclarationException("Enums are limited to 256 members!")
        self.members = members

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.members)
        return f"enum {self.name}({arg_types})"

    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments)})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "EnumPrimitive":
        """
        Generate an `Enum` object from an ABI interface.

        Arguments
        ---------
        abi : dict
            An object from a JSON ABI interface, representing an enum.

        Returns
        -------
        Enum object.
        """
        raise UnimplementedException("enum from ABI")

    @classmethod
    def from_EnumDef(cls, base_node: vy_ast.EnumDef) -> "EnumPrimitive":
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
            raise EnumDeclarationException("Enum must have members")

        for i, node in enumerate(base_node.body):
            member_name = node.value.id
            if member_name in members:
                raise EnumDeclarationException(
                    f"Enum member '{member_name}' has already been declared", node.value
                )

            members[member_name] = i

        return cls(base_node.name, members)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        # TODO
        return None

    def to_abi_dict(self) -> List[Dict]:
        # TODO
        return []

    def get_member(self, key: str, node: vy_ast.Attribute) -> EnumDefinition:
        if key in self.members:
            return self.from_annotation(node.value)
        suggestions_str = get_levenshtein_error_suggestions(key, self.members, 0.3)
        raise UnknownAttribute(f"{self} has no member '{key}'. {suggestions_str}", node)

    def from_annotation(
        self,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> EnumDefinition:
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type", node)
        return EnumDefinition(
            self.name, self.members, location, is_constant, is_public, is_immutable
        )
from collections import OrderedDict
from typing import Dict, List

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import EventDeclarationException, NamespaceCollision, StructureException
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation
from vyper.semantics.types.utils import get_type_from_abi, get_type_from_annotation
from vyper.semantics.validation.utils import validate_expected_type
from vyper.utils import keccak256


class Event:
    """
    Event type.

    Attributes
    ----------
    arguments : OrderedDict
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

    def __init__(self, name: str, arguments: OrderedDict, indexed: List) -> None:
        for key in arguments:
            validate_identifier(key)
        self.name = name
        self.arguments = arguments
        self.indexed = indexed
        self.event_id = int(keccak256(self.signature.encode()).hex(), 16)

    def __repr__(self):
        arg_types = ",".join(repr(a) for a in self.arguments.values())
        return f"event {self.name}({arg_types})"

    @property
    def signature(self):
        return f"{self.name}({','.join(v.canonical_abi_type for v in self.arguments.values())})"

    @classmethod
    def from_abi(cls, abi: Dict) -> "Event":
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
        members: OrderedDict = OrderedDict()
        indexed: List = [i["indexed"] for i in abi["inputs"]]
        for item in abi["inputs"]:
            members[item["name"]] = get_type_from_abi(item)
        return Event(abi["name"], members, indexed)

    @classmethod
    def from_EventDef(cls, base_node: vy_ast.EventDef) -> "Event":
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
        members: OrderedDict = OrderedDict()
        indexed: List = []

        if len(base_node.body) == 1 and isinstance(base_node.body[0], vy_ast.Pass):
            return Event(base_node.name, members, indexed)

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

            members[member_name] = get_type_from_annotation(annotation, DataLocation.UNSET)

        return Event(base_node.name, members, indexed)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, len(self.arguments))
        for arg, expected in zip(node.args, self.arguments.values()):
            validate_expected_type(arg, expected)

    def to_abi_dict(self) -> List[Dict]:
        return [
            {
                "name": self.name,
                "inputs": [
                    dict(**typ.to_abi_dict(name=k), **{"indexed": idx})
                    for (k, typ), idx in zip(self.arguments.items(), self.indexed)
                ],
                "anonymous": False,
                "type": "event",
            }
        ]
from . import enum, event, interface, struct

USER_TYPES = {"event": event, "interface": interface, "struct": struct, "enum": enum}
from collections import OrderedDict
from typing import Dict, List, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import InterfaceViolation, NamespaceCollision, StructureException
from vyper.semantics.namespace import get_namespace, validate_identifier
from vyper.semantics.types.bases import DataLocation, MemberTypeDefinition, ValueTypeDefinition
from vyper.semantics.types.function import ContractFunction
from vyper.semantics.types.user.event import Event
from vyper.semantics.types.value.address import AddressDefinition
from vyper.semantics.validation.utils import validate_expected_type, validate_unique_method_ids


class InterfaceDefinition(MemberTypeDefinition, ValueTypeDefinition):

    _type_members = {"address": AddressDefinition()}

    def __init__(
        self,
        _id: str,
        members: OrderedDict,
        location: DataLocation = DataLocation.MEMORY,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> None:
        self._id = _id
        super().__init__(location, is_constant, is_public, is_immutable)
        for key, type_ in members.items():
            self.add_member(key, type_)

    def get_signature(self):
        return (), AddressDefinition()

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()


class InterfacePrimitive:

    _is_callable = True
    _as_array = True

    def __init__(self, _id, members, events):
        validate_unique_method_ids(members.values())
        for key in members:
            validate_identifier(key)
        self._id = _id
        self.members = members
        self.events = events

    def __repr__(self):
        return f"{self._id} declaration object"

    def from_annotation(
        self,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.MEMORY,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> InterfaceDefinition:

        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)

        return InterfaceDefinition(
            self._id, self.members, location, is_constant, is_public, is_immutable
        )

    def fetch_call_return(self, node: vy_ast.Call) -> InterfaceDefinition:
        self.infer_arg_types(node)

        return InterfaceDefinition(self._id, self.members)

    def infer_arg_types(self, node):
        validate_call_args(node, 1)
        validate_expected_type(node.args[0], AddressDefinition())
        return [AddressDefinition()]

    def infer_kwarg_types(self, node):
        return {}

    def validate_implements(self, node: vy_ast.AnnAssign) -> None:
        namespace = get_namespace()
        # check for missing functions
        unimplemented = [
            name
            for name, type_ in self.members.items()
            if name not in namespace["self"].members
            or not hasattr(namespace["self"].members[name], "compare_signature")
            or not namespace["self"].members[name].compare_signature(type_)
        ]
        # check for missing events
        unimplemented += [
            name
            for name, event in self.events.items()
            if name not in namespace
            or not isinstance(namespace[name], Event)
            or namespace[name].event_id != event.event_id
        ]
        if unimplemented:
            missing_str = ", ".join(sorted(unimplemented))
            raise InterfaceViolation(
                f"Contract does not implement all interface functions or events: {missing_str}",
                node,
            )

    def to_abi_dict(self) -> List[Dict]:
        abi = []
        for event in self.events.values():
            abi += event.to_abi_dict()
        for func in self.members.values():
            abi += func.to_abi_dict()
        return abi


def build_primitive_from_abi(name: str, abi: dict) -> InterfacePrimitive:
    """
    Generate an `InterfacePrimitive` object from an ABI.

    Arguments
    ---------
    name : str
        The name of the interface
    abi : dict
        Contract ABI

    Returns
    -------
    InterfacePrimitive
        primitive interface type
    """
    members: OrderedDict = OrderedDict()
    events: Dict = {}

    names = [i["name"] for i in abi if i.get("type") in ("event", "function")]
    collisions = set(i for i in names if names.count(i) > 1)
    if collisions:
        collision_list = ", ".join(sorted(collisions))
        raise NamespaceCollision(
            f"ABI '{name}' has multiple functions or events with the same name: {collision_list}"
        )

    for item in [i for i in abi if i.get("type") == "function"]:
        members[item["name"]] = ContractFunction.from_abi(item)
    for item in [i for i in abi if i.get("type") == "event"]:
        events[item["name"]] = Event.from_abi(item)

    return InterfacePrimitive(name, members, events)


def build_primitive_from_node(
    node: Union[vy_ast.InterfaceDef, vy_ast.Module]
) -> InterfacePrimitive:
    """
    Generate an `InterfacePrimitive` object from a Vyper ast node.

    Arguments
    ---------
    node : InterfaceDef | Module
        Vyper ast node defining the interface
    Returns
    -------
    InterfacePrimitive
        primitive interface type
    """
    if isinstance(node, vy_ast.Module):
        members, events = _get_module_definitions(node)
    elif isinstance(node, vy_ast.InterfaceDef):
        members = _get_class_functions(node)
        events = {}
    else:
        raise StructureException("Invalid syntax for interface definition", node)

    return InterfacePrimitive(node.name, members, events)


def _get_module_definitions(base_node: vy_ast.Module) -> Tuple[OrderedDict, Dict]:
    functions: OrderedDict = OrderedDict()
    events: Dict = {}
    for node in base_node.get_children(vy_ast.FunctionDef):
        if "external" in [i.id for i in node.decorator_list if isinstance(i, vy_ast.Name)]:
            func = ContractFunction.from_FunctionDef(node)
            if node.name in functions:
                # compare the input arguments of the new function and the previous one
                # if one function extends the inputs, this is a valid function name overload
                existing_args = list(functions[node.name].arguments)
                new_args = list(func.arguments)
                for a, b in zip(existing_args, new_args):
                    if not isinstance(a, type(b)):
                        raise NamespaceCollision(
                            f"Interface contains multiple functions named '{node.name}' "
                            "with incompatible input types",
                            base_node,
                        )
                if len(new_args) <= len(existing_args):
                    # only keep the `ContractFunction` with the longest set of input args
                    continue
            functions[node.name] = func
    for node in base_node.get_children(vy_ast.AnnAssign, {"annotation.func.id": "public"}):
        name = node.target.id
        if name in functions:
            raise NamespaceCollision(
                f"Interface contains multiple functions named '{name}'", base_node
            )
        functions[name] = ContractFunction.from_AnnAssign(node)
    for node in base_node.get_children(vy_ast.EventDef):
        name = node.name
        if name in functions or name in events:
            raise NamespaceCollision(
                f"Interface contains multiple objects named '{name}'", base_node
            )
        events[name] = Event.from_EventDef(node)

    return functions, events


def _get_class_functions(base_node: vy_ast.InterfaceDef) -> OrderedDict:
    functions = OrderedDict()
    for node in base_node.body:
        if not isinstance(node, vy_ast.FunctionDef):
            raise StructureException("Interfaces can only contain function definitions", node)
        if node.name in functions:
            raise NamespaceCollision(
                f"Interface contains multiple functions named '{node.name}'", node
            )
        functions[node.name] = ContractFunction.from_FunctionDef(node, is_interface=True)

    return functions
from collections import OrderedDict

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Tuple, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    InvalidAttribute,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
    VariableDeclarationException,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.types.bases import DataLocation, MemberTypeDefinition, ValueTypeDefinition
from vyper.semantics.types.indexable.mapping import MappingDefinition
from vyper.semantics.types.utils import get_type_from_annotation
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.validation.utils import validate_expected_type


class StructT(AttributableT, SimpleGettableT):
    _is_callable = True
    _as_array = True

    def __init__(self, _id, members, ast_def):
        self._id = _id

        self.ast_def = ast_def

        for k, v in members:
            validate_identifier(k)
            self.add_member(k, v)

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
        members: List[Tuple(str, VyperType)] = {}
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
            members.append(member_name, type_from_annotation(node.annotation))

        return cls(struct_name, members, ast_def=base_node)

    def __repr__(self):
        return f"{self._id} declaration object"

    # TODO check me
    def compare_type(self, other):
        return super().compare_type(other) and self._id == other._id

    @property
    def size_in_bytes(self):
        return sum(i.size_in_bytes for i in self.members.values())

    @property
    def abi_type(self) -> ABIType:
        return ABI_Tuple([t.abi_type for t in self.members.values()])

    def to_abi_dict(self, name: str = "") -> dict:
        components = [t.to_abi_dict(name=k) for k, t in self.members.items()]
        return {"name": name, "type": "tuple", "components": components}

    # TODO breaking change: use kwargs instead of dict
    def fetch_call_return(self, node: vy_ast.Call) -> StructT:
        validate_call_args(node, 1)
        if not isinstance(node.args[0], vy_ast.Dict):
            raise VariableDeclarationException(
                "Struct values must be declared via dictionary", node.args[0]
            )
        if next((i for i in self.members.values() if isinstance(i, MappingDefinition)), False):
            raise VariableDeclarationException(
                "Struct contains a mapping and so cannot be declared as a literal", node
            )

        members = self.members.copy()
        keys = list(self.members.keys())
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
                    f"keys in this struct are {list(self.members.items())})",
                    key,
                )

            validate_expected_type(value, members.pop(key.id))

        if members:
            raise VariableDeclarationException(
                f"Struct declaration does not define all fields: {', '.join(list(members))}", node
            )

        return StructT(self._id, self.members)
