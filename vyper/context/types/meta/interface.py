from collections import OrderedDict
from typing import Union

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.context.namespace import get_namespace
from vyper.context.types.bases import DataLocation, MemberTypeDefinition
from vyper.context.types.function import ContractFunction
from vyper.context.types.value.address import AddressDefinition
from vyper.context.validation.utils import validate_expected_type
from vyper.exceptions import (
    InterfaceViolation,
    NamespaceCollision,
    StructureException,
)


class InterfaceDefinition(MemberTypeDefinition):

    _type_members = {"address": AddressDefinition()}

    def __init__(
        self,
        _id: str,
        members: OrderedDict,
        location: DataLocation = DataLocation.MEMORY,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        self._id = _id
        super().__init__(location, is_immutable, is_public)
        for key, type_ in members.items():
            self.add_member(key, type_)


class InterfacePrimitive:

    _is_callable = True
    _as_array = True

    def __init__(self, _id, members):
        self._id = _id
        self.members = members

    def __repr__(self):
        return f"{self._id} declaration object"

    def from_annotation(
        self,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.MEMORY,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> InterfaceDefinition:

        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)

        return InterfaceDefinition(self._id, self.members, location, is_immutable, is_public)

    def fetch_call_return(self, node: vy_ast.Call) -> InterfaceDefinition:
        validate_call_args(node, 1)
        validate_expected_type(node.args[0], AddressDefinition())

        return InterfaceDefinition(self._id, self.members)

    def validate_implements(self, node: vy_ast.AnnAssign) -> None:
        namespace = get_namespace()
        unimplemented = [
            name
            for name, type_ in self.members.items()
            if name not in namespace["self"].members
            or not hasattr(namespace["self"].members[name], "compare_signature")
            or not namespace["self"].members[name].compare_signature(type_)
        ]
        if unimplemented:
            raise InterfaceViolation(
                f"Contract does not implement all interface functions: {', '.join(unimplemented)}",
                node,
            )


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
    for item in [i for i in abi if i.get("type") == "function"]:
        func = ContractFunction.from_abi(item)
        if func.name in members:
            # TODO overloaded functions
            raise NamespaceCollision(
                f"ABI '{name}' contains multiple functions named '{func.name}'"
            )
        members[func.name] = func

    return InterfacePrimitive(name, members)


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
        members = _get_module_functions(node)
    elif isinstance(node, vy_ast.InterfaceDef):
        members = _get_class_functions(node)
    else:
        raise StructureException("Invalid syntax for interface definition", node)

    namespace = get_namespace()
    for func in members.values():
        if func.name in namespace:
            raise NamespaceCollision(func.name, func.node)

    return InterfacePrimitive(node.name, members)


def _get_module_functions(base_node: vy_ast.Module) -> OrderedDict:
    functions: OrderedDict = OrderedDict()
    for node in base_node.get_children(vy_ast.FunctionDef):
        if "external" in [i.id for i in node.decorator_list]:
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
    return functions


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
