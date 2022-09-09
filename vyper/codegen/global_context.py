from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import VariableRecord
from vyper.codegen.types import parse_type
from vyper.exceptions import CompilerPanic, InvalidType, StructureException
from vyper.semantics.types.user.enum import EnumPrimitive
from vyper.typing import InterfaceImports
from vyper.utils import cached_property


# Datatype to store all global context information.
# TODO: rename me to ModuleInfo
class GlobalContext:
    def __init__(self):
        # Oh jesus, just leave this. So confusing!
        self._contracts = dict()
        self._interfaces = dict()
        self._interface = dict()
        self._implemented_interfaces = set()

        self._structs = dict()
        self._events = list()
        self._enums = dict()
        self._globals = dict()
        self._function_defs = list()
        self._nonrentrant_counter = 0
        self._nonrentrant_keys = dict()

    # Parse top-level functions and variables
    @classmethod
    # TODO rename me to `from_module`
    def get_global_context(
        cls, vyper_module: "vy_ast.Module", interface_codes: Optional[InterfaceImports] = None
    ) -> "GlobalContext":
        # TODO is this a cyclic import?
        from vyper.ast.signatures.interface import extract_sigs, get_builtin_interfaces

        interface_codes = {} if interface_codes is None else interface_codes
        global_ctx = cls()

        for item in vyper_module:
            if isinstance(item, vy_ast.StructDef):
                global_ctx._structs[item.name] = global_ctx.make_struct(item)

            elif isinstance(item, vy_ast.InterfaceDef):
                global_ctx._contracts[item.name] = GlobalContext.make_contract(item)

            elif isinstance(item, vy_ast.EventDef):
                continue

            elif isinstance(item, vy_ast.EnumDef):
                global_ctx._enums[item.name] = EnumPrimitive.from_EnumDef(item)

            # Statements of the form:
            # variable_name: type
            elif isinstance(item, vy_ast.VariableDecl):
                global_ctx.add_globals_and_events(item)
            # Function definitions
            elif isinstance(item, vy_ast.FunctionDef):
                global_ctx._function_defs.append(item)
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
                self.parse_type(member_type)
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

    def add_globals_and_events(self, item):

        if self._nonrentrant_counter:
            raise CompilerPanic("Re-entrancy lock was set before all storage slots were defined")

        # Make sure we have a valid variable name.
        if not isinstance(item.target, vy_ast.Name):
            raise StructureException("Invalid global variable name", item.target)

        # Handle constants.
        if item.is_constant:
            return

        # references to `len(self._globals)` are remnants of deprecated code, retained
        # to preserve existing interfaces while we complete a larger refactor. location
        # and size of storage vars is handled in `vyper.context.validation.data_positions`
        typ = self.parse_type(item.annotation)
        is_immutable = item.is_immutable
        self._globals[item.target.id] = VariableRecord(
            item.target.id,
            len(self._globals),
            typ,
            mutable=not is_immutable,
            is_immutable=is_immutable,
        )

    @property
    def interface_names(self):
        """
        The set of names which are known to possibly be InterfaceType
        """
        return set(self._contracts.keys()) | set(self._interfaces.keys())

    def parse_type(self, ast_node):
        return parse_type(
            ast_node, sigs=self.interface_names, custom_structs=self._structs, enums=self._enums
        )

    @property
    def immutables(self):
        return [t for t in self._globals.values() if t.is_immutable]

    @cached_property
    def immutable_section_bytes(self):
        return sum([imm.size * 32 for imm in self.immutables])
