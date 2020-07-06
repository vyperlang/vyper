from typing import Optional

from vyper import ast as vy_ast
from vyper.exceptions import (
    InvalidType,
    StructureException,
    VariableDeclarationException,
)
from vyper.parser.parser_utils import getpos, set_offsets
from vyper.signatures.function_signature import ContractRecord, VariableRecord
from vyper.types import (
    BaseType,
    ByteArrayLike,
    InterfaceType,
    ListType,
    MappingType,
    StructType,
    parse_type,
)
from vyper.typing import InterfaceImports
from vyper.utils import VALID_GLOBAL_KEYWORDS, check_valid_varname

NONRENTRANT_STORAGE_OFFSET = 0xFFFFFF


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
        self._getters = list()
        self._nonrentrant_counter = 0
        self._nonrentrant_keys = dict()

    # Parse top-level functions and variables
    @classmethod
    def get_global_context(
        cls, vyper_module: "vy_ast.Module", interface_codes: Optional[InterfaceImports] = None
    ) -> "GlobalContext":
        from vyper.signatures.interface import (
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
                global_ctx._events.append(item)

            # Statements of the form:
            # variable_name: type
            elif isinstance(item, vy_ast.AnnAssign):
                is_implements_statement = (
                    isinstance(item.target, vy_ast.Name) and item.target.id == "implements"
                ) and item.annotation

                # implements statement.
                if is_implements_statement:
                    interface_name = item.annotation.id  # type: ignore
                    if interface_name not in global_ctx._interfaces:
                        raise StructureException(
                            f"Unknown interface specified: {interface_name}", item
                        )
                    global_ctx._implemented_interfaces.add(interface_name)
                else:
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

        # Add getters to _defs
        global_ctx._defs += global_ctx._getters
        return global_ctx

    # Make a getter for a variable. This function gives an output that
    # contains lists of 4-tuples:
    # (i) the tail of the function name for the getter
    # (ii) the code for the arguments that the function takes
    # (iii) the code for the return
    # (iv) the output type
    #
    # Here is an example:
    #
    # Input: my_variable: {foo: int128, bar: decimal[5]}
    #
    # Output:
    #
    # [('__foo', '', '.foo', 'int128'),
    #  ('__bar', 'arg0: int128, ', '.bar[arg0]', 'decimal')]
    #
    # The getters will have code:
    # def get_my_variable__foo() -> int128: return self.foo
    # def get_my_variable__bar(arg0: nun) -> decimal: return self.bar[arg0]

    @classmethod
    def _mk_getter_helper(cls, typ, depth=0):
        # Base type and byte array type: do not extend the getter function
        # name, add no input arguments, add nothing to the return statement,
        # output type is the base type
        if isinstance(typ, (BaseType, ByteArrayLike)):
            return [("", "", "", repr(typ))]
        # List type: do not extend the getter name, add an input argument for
        # the index in the list, add an item access to the return statement
        elif isinstance(typ, ListType):
            o = []
            for funname, head, tail, base in cls._mk_getter_helper(typ.subtype, depth + 1):
                o.append(
                    (funname, (f"arg{depth}: uint256, ") + head, (f"[arg{depth}]") + tail, base,)
                )
            return o
        # Mapping type: do not extend the getter name, add an input argument for
        # the key in the map, add a value access to the return statement
        elif isinstance(typ, MappingType):
            o = []
            for funname, head, tail, base in cls._mk_getter_helper(typ.valuetype, depth + 1):
                o.append(
                    (
                        funname,
                        (f"arg{depth}: {typ.keytype}, ") + head,
                        (f"[arg{depth}]") + tail,
                        base,
                    )
                )
            return o
        # Struct type: return type is just the abi-encoded struct
        elif isinstance(typ, StructType):
            return [("", "", "", typ.name)]
        else:
            raise Exception("Unexpected type")

    # Make a list of getters for a given variable name with a given type
    @classmethod
    def mk_getter(cls, varname, typ):
        funs = cls._mk_getter_helper(typ)
        return [
            f"""@view
@external
def {varname}{funname}({head.rstrip(', ')}) -> {base}:
    return self.{varname}{tail}"""
            for (funname, head, tail, base) in funs  # noqa: E501
        ]

    # Parser for a single line
    @staticmethod
    def parse_line(source_code: str) -> list:
        parsed_ast = vy_ast.parse_to_ast(source_code)[0]
        return parsed_ast

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
                check_valid_varname(
                    member_name.id, self._structs, item, "Invalid member name for struct. ",
                )
                # Check well-formedness of member types
                # Note this kicks out mutually recursive structs,
                # raising an exception instead of stackoverflow.
                # A struct must be defined before it is referenced.
                # This feels like a semantic step and maybe should be pushed
                # to a later compilation stage.
                parse_type(
                    member_type, "storage", custom_structs=self._structs,
                )
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

    def is_valid_varname(self, name, item):
        """ Valid variable name, checked against global context. """
        check_valid_varname(name, self._structs, item)
        if name in self._globals:
            raise VariableDeclarationException(
                f'Invalid name "{name}", previously defined as global.', item
            )
        return True

    @staticmethod
    def get_call_func_name(item):
        if isinstance(item.annotation, vy_ast.Call) and isinstance(
            item.annotation.func, vy_ast.Name
        ):
            return item.annotation.func.id

    def add_globals_and_events(self, item):
        item_attributes = {"public": False}

        if len(self._globals) > NONRENTRANT_STORAGE_OFFSET:
            raise StructureException(
                f"Too many globals defined, only {NONRENTRANT_STORAGE_OFFSET} globals are allowed",
                item,
            )

        # Make sure we have a valid variable name.
        if not isinstance(item.target, vy_ast.Name):
            raise StructureException("Invalid global variable name", item.target)

        # Handle constants.
        if self.get_call_func_name(item) == "constant":
            self.is_valid_varname(item.target.id, item)
            return

        item_name, item_attributes = self.get_item_name_and_attributes(item, item_attributes)
        if not all([attr in VALID_GLOBAL_KEYWORDS for attr in item_attributes.keys()]):
            raise StructureException(f"Invalid global keyword used: {item_attributes}", item)
        self.is_valid_varname(item.target.id, item)

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
            if item_attributes["public"]:
                typ = InterfaceType(item_name)
                for getter in self.mk_getter(item.target.id, typ):
                    self._getters.append(self.parse_line("\n" * (item.lineno - 1) + getter))
                    self._getters[-1].pos = getpos(item)
                    set_offsets(self._getters[-1], self._getters[-1].pos)
        elif self.get_call_func_name(item) == "public":
            if isinstance(item.annotation.args[0], vy_ast.Name) and item_name in self._contracts:
                typ = InterfaceType(item_name)
            else:
                typ = parse_type(item.annotation.args[0], "storage", custom_structs=self._structs,)
            self._globals[item.target.id] = VariableRecord(
                item.target.id, len(self._globals), typ, True,
            )
            # Adding getters here
            for getter in self.mk_getter(item.target.id, typ):
                self._getters.append(self.parse_line("\n" * (item.lineno - 1) + getter))
                self._getters[-1].pos = getpos(item)
                set_offsets(self._getters[-1], self._getters[-1].pos)

        elif isinstance(item.annotation, (vy_ast.Name, vy_ast.Call, vy_ast.Subscript)):
            self._globals[item.target.id] = VariableRecord(
                item.target.id,
                len(self._globals),
                parse_type(item.annotation, "storage", custom_structs=self._structs,),
                True,
            )
        else:
            raise InvalidType("Invalid global type specified", item)

    def parse_type(self, ast_node, location):
        return parse_type(ast_node, location, sigs=self._contracts, custom_structs=self._structs,)

    def get_nonrentrant_counter(self, key):
        """
        Nonrentrant locks use a prefix with a counter to minimise deployment cost of a contract.
        """
        prefix = NONRENTRANT_STORAGE_OFFSET

        if key in self._nonrentrant_keys:
            return self._nonrentrant_keys[key]
        else:
            counter = prefix + self._nonrentrant_counter
            self._nonrentrant_keys[key] = counter
            self._nonrentrant_counter += 1
            return counter
