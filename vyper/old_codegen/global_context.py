from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import (
    ContractRecord,
    VariableRecord,
)
from vyper.exceptions import CompilerPanic, InvalidType, StructureException
from vyper.old_codegen.types import InterfaceType, parse_type
from vyper.typing import InterfaceImports


# Datatype to store all global context information.
class GlobalContext:
    def __init__(self):
        # Oh jesus, just leave this. So confusing!
        self._contracts = dict()
        self._interfaces = dict()
        self._interface = dict()
        self._implemented_interfaces = set()

        self._structs = dict()
        self._events = list()
        self._globals = dict()
        self._defs = list()
        self._nonrentrant_counter = 0
        self._nonrentrant_keys = dict()

    # Parse top-level functions and variables
    @classmethod
    def get_global_context(
        cls, vyper_module: "vy_ast.Module", interface_codes: Optional[InterfaceImports] = None
    ) -> "GlobalContext":
        # TODO is this a cyclic import?
        from vyper.ast.signatures.interface import (
            extract_sigs,
            get_builtin_interfaces,
        )

        interface_codes = {} if interface_codes is None else interface_codes
        global_ctx = cls()

        for item in vyper_module:
            if isinstance(item, vy_ast.StructDef):
                global_ctx._structs[item.name] = global_ctx.make_struct(item)

            elif isinstance(item, vy_ast.InterfaceDef):
                global_ctx._contracts[item.name] = GlobalContext.make_contract(item)

            elif isinstance(item, vy_ast.EventDef):
                continue

            # Statements of the form:
            # variable_name: type
            elif isinstance(item, vy_ast.AnnAssign):
                global_ctx.add_globals_and_events(item)
            # Function definitions
            elif isinstance(item, vy_ast.FunctionDef):
                global_ctx._defs.append(item)
            elif isinstance(item, vy_ast.ImportFrom):
                interface_name = item.name
                assigned_name = item.alias or item.name
                if assigned_name in global_ctx._interfaces:
                    raise StructureException(f"Duplicate import of {interface_name}", item)

                if not item.level and item.module == "vyper.interfaces":
                    built_in_interfaces = get_builtin_interfaces()
                    if interface_name not in built_in_interfaces:
                        raise StructureException(
                            f"Built-In interface {interface_name} does not exist.", item
                        )
                    global_ctx._interfaces[assigned_name] = built_in_interfaces[
                        interface_name
                    ].copy()
                else:
                    if interface_name not in interface_codes:
                        raise StructureException(f"Unknown interface {interface_name}", item)
                    global_ctx._interfaces[assigned_name] = extract_sigs(
                        interface_codes[interface_name], interface_name
                    )
            elif isinstance(item, vy_ast.Import):
                interface_name = item.alias
                if interface_name in global_ctx._interfaces:
                    raise StructureException(f"Duplicate import of {interface_name}", item)
                if interface_name not in interface_codes:
                    raise StructureException(f"Unknown interface {interface_name}", item)
                global_ctx._interfaces[interface_name] = extract_sigs(
                    interface_codes[interface_name], interface_name
                )
            else:
                raise StructureException("Invalid top-level statement", item)

        # Merge intefaces.
        if global_ctx._interfaces:
            for interface_name, sigs in global_ctx._interfaces.items():
                if interface_name in global_ctx._implemented_interfaces:
                    for func_sig in sigs:
                        func_sig.defined_in_interface = interface_name
                        global_ctx._interface[func_sig.sig] = func_sig

        return global_ctx

    # A struct is a list of members
    def make_struct(self, node: "vy_ast.StructDef") -> list:
        members = []

        for item in node.body:
            if isinstance(item, vy_ast.AnnAssign):
                member_name = item.target
                member_type = item.annotation
                # Check well-formedness of member names
                if not isinstance(member_name, vy_ast.Name):
                    raise InvalidType(
                        f"Invalid member name for struct {node.name}, needs to be a valid name. ",
                        item,
                    )
                # Check well-formedness of member types
                # Note this kicks out mutually recursive structs,
                # raising an exception instead of stackoverflow.
                # A struct must be defined before it is referenced.
                # This feels like a semantic step and maybe should be pushed
                # to a later compilation stage.
                self.parse_type(member_type, "storage")
                members.append((member_name, member_type))
            else:
                raise StructureException("Structs can only contain variables", item)
        return members

    # A contract is a list of functions.
    @staticmethod
    def make_contract(node: "vy_ast.InterfaceDef") -> list:
        _defs = []
        for item in node.body:
            # Function definitions
            if isinstance(item, vy_ast.FunctionDef):
                _defs.append(item)
            else:
                raise StructureException("Invalid contract reference", item)
        return _defs

    def get_item_name_and_attributes(self, item, attributes):
        is_map_invocation = (
            isinstance(item, vy_ast.Call) and isinstance(item.func, vy_ast.Name)
        ) and item.func.id == "HashMap"

        if isinstance(item, vy_ast.Name):
            return item.id, attributes
        elif isinstance(item, vy_ast.AnnAssign):
            return self.get_item_name_and_attributes(item.annotation, attributes)
        elif isinstance(item, vy_ast.Subscript):
            return self.get_item_name_and_attributes(item.value, attributes)
        elif is_map_invocation:
            if len(item.args) != 2:
                raise StructureException(
                    "Map type expects two type arguments HashMap[type1, type2]", item.func
                )
            return self.get_item_name_and_attributes(item.args, attributes)
        # elif ist
        elif isinstance(item, vy_ast.Call) and isinstance(item.func, vy_ast.Name):
            attributes[item.func.id] = True
            # Raise for multiple args
            if len(item.args) != 1:
                raise StructureException(f"{item.func.id} expects one arg (the type)")
            return self.get_item_name_and_attributes(item.args[0], attributes)
        return None, attributes

    @staticmethod
    def get_call_func_name(item):
        if isinstance(item.annotation, vy_ast.Call) and isinstance(
            item.annotation.func, vy_ast.Name
        ):
            return item.annotation.func.id

    def add_globals_and_events(self, item):
        item_attributes = {"public": False}

        if self._nonrentrant_counter:
            raise CompilerPanic("Re-entrancy lock was set before all storage slots were defined")

        # Make sure we have a valid variable name.
        if not isinstance(item.target, vy_ast.Name):
            raise StructureException("Invalid global variable name", item.target)

        # Handle constants.
        if self.get_call_func_name(item) == "constant":
            return

        item_name, item_attributes = self.get_item_name_and_attributes(item, item_attributes)

        # references to `len(self._globals)` are remnants of deprecated code, retained
        # to preserve existing interfaces while we complete a larger refactor. location
        # and size of storage vars is handled in `vyper.context.validation.data_positions`
        if item_name in self._contracts or item_name in self._interfaces:
            if self.get_call_func_name(item) == "address":
                raise StructureException(
                    f"Persistent address({item_name}) style contract declarations "
                    "are not support anymore."
                    f" Use {item.target.id}: {item_name} instead"
                )
            self._globals[item.target.id] = ContractRecord(
                item.target.id, len(self._globals), InterfaceType(item_name), True,
            )
        elif self.get_call_func_name(item) == "public":
            if isinstance(item.annotation.args[0], vy_ast.Name) and item_name in self._contracts:
                typ = InterfaceType(item_name)
            else:
                typ = self.parse_type(item.annotation.args[0], "storage")
            self._globals[item.target.id] = VariableRecord(
                item.target.id, len(self._globals), typ, True,
            )

        elif isinstance(item.annotation, (vy_ast.Name, vy_ast.Call, vy_ast.Subscript)):
            self._globals[item.target.id] = VariableRecord(
                item.target.id,
                len(self._globals),
                self.parse_type(item.annotation, "storage"),
                True,
            )
        else:
            raise InvalidType("Invalid global type specified", item)

    def parse_type(self, ast_node, location):
        return parse_type(ast_node, location, sigs=self._contracts, custom_structs=self._structs,)
