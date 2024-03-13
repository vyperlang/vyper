from functools import cached_property
from typing import TYPE_CHECKING, Optional

from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABIType
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    InterfaceViolation,
    NamespaceCollision,
    StructureException,
    UnfoldableNode,
)
from vyper.semantics.analysis.base import Modifiability
from vyper.semantics.analysis.utils import (
    check_modifiability,
    get_exact_type_from_node,
    validate_expected_type,
    validate_unique_method_ids,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import TYPE_T, VyperType, is_type_t
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.primitives import AddressT
from vyper.semantics.types.user import EventT, StructT, _UserType
from vyper.utils import OrderedSet

if TYPE_CHECKING:
    from vyper.semantics.analysis.base import ModuleInfo


class InterfaceT(_UserType):
    typeclass = "interface"

    _type_members = {"address": AddressT()}
    _is_prim_word = True
    _as_array = True
    _as_hashmap_key = True
    _supports_external_calls = True
    _attribute_in_annotation = True

    def __init__(
        self,
        _id: str,
        decl_node: Optional[vy_ast.VyperNode],
        functions: dict,
        events: dict,
        structs: dict,
    ) -> None:
        validate_unique_method_ids(list(functions.values()))

        members = functions | events | structs

        # sanity check: by construction, there should be no duplicates.
        assert len(members) == len(functions) + len(events) + len(structs)

        super().__init__(functions)

        self._helper = VyperType(events | structs)
        self._id = _id
        self._helper._id = _id
        self.functions = functions
        self.events = events
        self.structs = structs

        self.decl_node = decl_node

    def get_type_member(self, attr, node):
        # get an event or struct from this interface
        return TYPE_T(self._helper.get_member(attr, node))

    @property
    def getter_signature(self):
        return (), AddressT()

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()

    def __repr__(self):
        return f"interface {self._id}"

    def _try_fold(self, node):
        if len(node.args) != 1:
            raise UnfoldableNode("wrong number of args", node.args)
        arg = node.args[0].get_folded_value()
        if not isinstance(arg, vy_ast.Hex):
            raise UnfoldableNode("not an address", arg)

        return node

    # when using the type itself (not an instance) in the call position
    def _ctor_call_return(self, node: vy_ast.Call) -> "InterfaceT":
        self._ctor_arg_types(node)
        return self

    def _ctor_arg_types(self, node):
        validate_call_args(node, 1)
        validate_expected_type(node.args[0], AddressT())
        return [AddressT()]

    def _ctor_kwarg_types(self, node):
        return {}

    def _ctor_modifiability_for_call(self, node: vy_ast.Call, modifiability: Modifiability) -> bool:
        return check_modifiability(node.args[0], modifiability)

    def validate_implements(
        self, node: vy_ast.ImplementsDecl, functions: dict[ContractFunctionT, vy_ast.VyperNode]
    ) -> None:
        fns_by_name = {fn_t.name: fn_t for fn_t in functions.keys()}

        unimplemented = []

        def _is_function_implemented(fn_name, fn_type):
            if fn_name not in fns_by_name:
                return False

            to_compare = fns_by_name[fn_name]
            assert isinstance(to_compare, ContractFunctionT)

            return to_compare.implements(fn_type)

        # check for missing functions
        for name, type_ in self.functions.items():
            if not isinstance(type_, ContractFunctionT):
                # ex. address
                continue

            if not _is_function_implemented(name, type_):
                unimplemented.append(name)

        if len(unimplemented) > 0:
            # TODO: improve the error message for cases where the
            # mismatch is small (like mutability, or just one argument
            # is off, etc).
            missing_str = ", ".join(sorted(unimplemented))
            raise InterfaceViolation(
                f"Contract does not implement all interface functions: {missing_str}", node
            )

    def to_toplevel_abi_dict(self) -> list[dict]:
        abi = []
        for event in self.events.values():
            abi += event.to_toplevel_abi_dict()
        for func in self.functions.values():
            abi += func.to_toplevel_abi_dict()
        return abi

    # helper function which performs namespace collision checking
    @classmethod
    def _from_lists(
        cls,
        interface_name: str,
        decl_node: Optional[vy_ast.VyperNode],
        function_list: list[tuple[str, ContractFunctionT]],
        event_list: list[tuple[str, EventT]],
        struct_list: list[tuple[str, StructT]],
    ) -> "InterfaceT":
        functions = {}
        events = {}
        structs = {}

        seen_items: dict = {}

        def _mark_seen(name, item):
            if name in seen_items:
                msg = f"multiple functions or events named '{name}'!"
                prev_decl = seen_items[name].decl_node
                raise NamespaceCollision(msg, item.decl_node, prev_decl=prev_decl)
            seen_items[name] = item

        for name, function in function_list:
            _mark_seen(name, function)
            functions[name] = function

        for name, event in event_list:
            _mark_seen(name, event)
            events[name] = event

        for name, struct in struct_list:
            _mark_seen(name, struct)
            structs[name] = struct

        return cls(interface_name, decl_node, functions, events, structs)

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
        functions: list = []
        events: list = []

        for item in [i for i in abi if i.get("type") == "function"]:
            functions.append((item["name"], ContractFunctionT.from_abi(item)))
        for item in [i for i in abi if i.get("type") == "event"]:
            events.append((item["name"], EventT.from_abi(item)))

        structs: list = []  # no structs in json ABI (as of yet)
        return cls._from_lists(name, None, functions, events, structs)

    @classmethod
    def from_ModuleT(cls, module_t: "ModuleT") -> "InterfaceT":
        """
        Generate an `InterfaceT` object from a Vyper ast node.

        Arguments
        ---------
        module_t: ModuleT
            Vyper module type
        Returns
        -------
        InterfaceT
            primitive interface type
        """
        funcs = []

        for fn_t in module_t.exposed_functions:
            funcs.append((fn_t.name, fn_t))

        if (fn_t := module_t.init_function) is not None:
            funcs.append((fn_t.name, fn_t))

        event_set: OrderedSet[EventT] = OrderedSet()
        event_set.update([node._metadata["event_type"] for node in module_t.event_defs])
        event_set.update(module_t.used_events)
        events = [(event_t.name, event_t) for event_t in event_set]

        # these are accessible via import, but they do not show up
        # in the ABI json
        structs = [(node.name, node._metadata["struct_type"]) for node in module_t.struct_defs]

        return cls._from_lists(module_t._id, module_t.decl_node, funcs, events, structs)

    @classmethod
    def from_InterfaceDef(cls, node: vy_ast.InterfaceDef) -> "InterfaceT":
        functions = []
        for func_ast in node.body:
            if not isinstance(func_ast, vy_ast.FunctionDef):
                raise StructureException(
                    "Interfaces can only contain function definitions", func_ast
                )
            if len(func_ast.decorator_list) > 0:
                raise StructureException(
                    "Function definition in interface cannot be decorated",
                    func_ast.decorator_list[0],
                )
            functions.append((func_ast.name, ContractFunctionT.from_InterfaceDef(func_ast)))

        # no structs or events in InterfaceDefs
        events: list = []
        structs: list = []

        return cls._from_lists(node.name, node, functions, events, structs)


# Datatype to store all module information.
class ModuleT(VyperType):
    typeclass = "module"

    _attribute_in_annotation = True
    _invalid_locations = (
        DataLocation.CALLDATA,
        DataLocation.CODE,
        DataLocation.MEMORY,
        DataLocation.TRANSIENT,
    )

    def __init__(self, module: vy_ast.Module, name: Optional[str] = None):
        super().__init__()

        self._module = module

        self._id = name or module.path

        # compute the interface, note this has the side effect of checking
        # for function collisions
        _ = self.interface

        self._helper = VyperType()
        self._helper._id = self._id

        for f in self.function_defs:
            # note: this checks for collisions
            self.add_member(f.name, f._metadata["func_type"])

        for e in self.event_defs:
            # add the type of the event so it can be used in call position
            self.add_member(e.name, TYPE_T(e._metadata["event_type"]))  # type: ignore

        for s in self.struct_defs:
            # add the type of the struct so it can be used in call position
            self.add_member(s.name, TYPE_T(s._metadata["struct_type"]))  # type: ignore
            self._helper.add_member(s.name, TYPE_T(s._metadata["struct_type"]))  # type: ignore

        for i in self.interface_defs:
            # add the type of the interface so it can be used in call position
            self.add_member(i.name, TYPE_T(i._metadata["interface_type"]))  # type: ignore

        for v in self.variable_decls:
            self.add_member(v.target.id, v.target._metadata["varinfo"])

        for i in self.import_stmts:
            import_info = i._metadata["import_info"]
            self.add_member(import_info.alias, import_info.typ)

            if hasattr(import_info.typ, "module_t"):
                self._helper.add_member(import_info.alias, TYPE_T(import_info.typ))

        for name, interface_t in self.interfaces.items():
            # can access interfaces in type position
            self._helper.add_member(name, TYPE_T(interface_t))

    # __eq__ is very strict on ModuleT - object equality! this is because we
    # don't want to reason about where a module came from (i.e. input bundle,
    # search path, symlinked vs normalized path, etc.)
    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(id(self))

    @property
    def decl_node(self) -> Optional[vy_ast.VyperNode]:  # type: ignore[override]
        return self._module

    def get_type_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        return self._helper.get_member(key, node)

    @cached_property
    def function_defs(self):
        return self._module.get_children(vy_ast.FunctionDef)

    @cached_property
    def event_defs(self):
        return self._module.get_children(vy_ast.EventDef)

    @property
    def struct_defs(self):
        return self._module.get_children(vy_ast.StructDef)

    @property
    def interface_defs(self):
        return self._module.get_children(vy_ast.InterfaceDef)

    @cached_property
    def implements_decls(self):
        return self._module.get_children(vy_ast.ImplementsDecl)

    @cached_property
    def interfaces(self) -> dict[str, InterfaceT]:
        ret = {}
        for i in self.interface_defs:
            assert i.name not in ret  # precondition
            ret[i.name] = i._metadata["interface_type"]

        for i in self.import_stmts:
            import_info = i._metadata["import_info"]
            if isinstance(import_info.typ, InterfaceT):
                assert import_info.alias not in ret  # precondition
                ret[import_info.alias] = import_info.typ

        return ret

    @property
    def import_stmts(self):
        return self._module.get_children((vy_ast.Import, vy_ast.ImportFrom))

    @cached_property
    def imported_modules(self) -> dict[str, "ModuleInfo"]:
        ret = {}
        for s in self.import_stmts:
            info = s._metadata["import_info"]
            module_info = info.typ
            if isinstance(module_info, InterfaceT):
                continue
            ret[info.alias] = module_info
        return ret

    def find_module_info(self, needle: "ModuleT") -> Optional["ModuleInfo"]:
        for s in self.imported_modules.values():
            if s.module_t == needle:
                return s
        return None

    @property
    def variable_decls(self):
        return self._module.get_children(vy_ast.VariableDecl)

    @property
    def uses_decls(self):
        return self._module.get_children(vy_ast.UsesDecl)

    @property
    def initializes_decls(self):
        return self._module.get_children(vy_ast.InitializesDecl)

    @property
    def exports_decls(self):
        return self._module.get_children(vy_ast.ExportsDecl)

    @cached_property
    def used_modules(self):
        # modules which are written to
        ret = []
        for node in self.uses_decls:
            for used_module in node._metadata["uses_info"].used_modules:
                ret.append(used_module)
        return ret

    @property
    def initialized_modules(self):
        # modules which are initialized to
        ret = []
        for node in self.initializes_decls:
            info = node._metadata["initializes_info"]
            ret.append(info)
        return ret

    @cached_property
    def exposed_functions(self):
        # return external functions that are exposed in the runtime
        ret = []
        for node in self.exports_decls:
            ret.extend(node._metadata["exports_info"].functions)

        ret.extend([f for f in self.functions.values() if f.is_external])
        ret.extend([v.getter_ast._metadata["func_type"] for v in self.public_variables.values()])

        # precondition: no duplicate exports
        assert len(set(ret)) == len(ret)

        return ret

    @cached_property
    def init_function(self) -> Optional[ContractFunctionT]:
        return next((f for f in self.functions.values() if f.is_constructor), None)

    @cached_property
    def variables(self):
        # variables that this module defines, ex.
        # `x: uint256` is a private storage variable named x
        return {s.target.id: s.target._metadata["varinfo"] for s in self.variable_decls}

    @cached_property
    def public_variables(self):
        return {k: v for (k, v) in self.variables.items() if v.is_public}

    @cached_property
    def functions(self):
        return {f.name: f._metadata["func_type"] for f in self.function_defs}

    @cached_property
    # it would be nice to rely on the function analyzer to do this analysis,
    # but we don't have the result of function analysis at the time we need to
    # construct `self.interface`.
    def used_events(self) -> OrderedSet[EventT]:
        ret: OrderedSet[EventT] = OrderedSet()

        reachable: OrderedSet[ContractFunctionT] = OrderedSet()
        if self.init_function is not None:
            reachable.add(self.init_function)
            reachable.update(self.init_function.reachable_internal_functions)
        for fn_t in self.exposed_functions:
            reachable.add(fn_t)
            reachable.update(fn_t.reachable_internal_functions)

        for fn_t in reachable:
            fn_ast = fn_t.decl_node
            assert isinstance(fn_ast, vy_ast.FunctionDef)

            for node in fn_ast.get_descendants(vy_ast.Log):
                call_t = get_exact_type_from_node(node.value.func)
                if not is_type_t(call_t, EventT):
                    # this is an error, but it will be handled later
                    continue

                ret.add(call_t.typedef)

        return ret

    @cached_property
    def immutables(self):
        return [t for t in self.variables.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        ret = 0
        for s in self.immutables:
            ret += s.typ.memory_bytes_required

        for initializes_info in self.initialized_modules:
            module_t = initializes_info.module_info.module_t
            ret += module_t.immutable_section_bytes

        return ret

    @cached_property
    def interface(self):
        return InterfaceT.from_ModuleT(self)
