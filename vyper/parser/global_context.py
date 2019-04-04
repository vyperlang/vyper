from vyper import ast
from vyper.ast_utils import (
    parse_to_ast,
)
from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    InvalidTypeException,
    ParserException,
    StructureException,
    VariableDeclarationException,
)
from vyper.parser.constants import (
    Constants,
)
from vyper.parser.parser_utils import (
    getpos,
)
from vyper.signatures.function_signature import (
    ContractRecord,
    VariableRecord,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ContractType,
    ListType,
    MappingType,
    StructType,
    parse_type,
)
from vyper.utils import (
    check_valid_varname,
    valid_global_keywords,
)

NONRENTRANT_STORAGE_OFFSET = 0xffffff


# Datatype to store all global context information.
class GlobalContext:
    def __init__(self):
        self._contracts = dict()
        self._structs = dict()
        self._events = list()
        self._globals = dict()
        self._defs = list()
        self._getters = list()
        self._custom_units = set()
        self._custom_units_descriptions = dict()
        self._constants = Constants()
        self._interfaces = dict()
        self._interface = dict()
        self._implemented_interfaces = set()
        self._nonrentrant_counter = 0
        self._nonrentrant_keys = dict()

    # Parse top-level functions and variables
    @classmethod
    def get_global_context(cls, code, interface_codes=None):
        from vyper.signatures.interface import (
            extract_sigs,
            get_builtin_interfaces,
        )
        interface_codes = {} if interface_codes is None else interface_codes
        global_ctx = cls()

        for item in code:
            # Contract references
            if isinstance(item, ast.ClassDef):
                if global_ctx._events or global_ctx._globals or global_ctx._defs:
                    raise StructureException((
                        "External contract and struct declarations must come "
                        "before event declarations, global declarations, and "
                        "function definitions"
                    ), item)

                if item.class_type == 'struct':
                    if global_ctx._contracts:
                        raise StructureException(
                            "Structs must come before external contract definitions", item
                        )
                    global_ctx._structs[item.name] = global_ctx.make_struct(item.name, item.body)
                elif item.class_type == 'contract':
                    if item.name in global_ctx._contracts or item.name in global_ctx._interfaces:
                        raise StructureException(
                            "Contract '{}' is already defined".format(item.name),
                            item,
                        )
                    global_ctx._contracts[item.name] = GlobalContext.make_contract(item.body)
                else:
                    raise StructureException(
                        "Unknown class_type. This is likely a compiler bug, please report", item
                    )

            # Statements of the form:
            # variable_name: type
            elif isinstance(item, ast.AnnAssign):
                is_implements_statement = (
                    isinstance(item.target, ast.Name) and item.target.id == 'implements'
                ) and item.annotation

                # implements statement.
                if is_implements_statement:
                    interface_name = item.annotation.id
                    if interface_name not in global_ctx._interfaces:
                        raise StructureException(
                            'Unknown interface specified: {}'.format(interface_name), item
                        )
                    global_ctx._implemented_interfaces.add(interface_name)
                else:
                    global_ctx.add_globals_and_events(item)
            # Function definitions
            elif isinstance(item, ast.FunctionDef):
                if item.name in global_ctx._globals:
                    raise FunctionDeclarationException(
                        "Function name shadowing a variable name: %s" % item.name
                    )
                global_ctx._defs.append(item)
            elif isinstance(item, ast.ImportFrom):
                if item.module == 'vyper.interfaces':
                    built_in_interfaces = get_builtin_interfaces()
                    for item_alias in item.names:
                        interface_name = item_alias.name
                        if interface_name in global_ctx._interfaces:
                            raise StructureException(
                                'Duplicate import of {}'.format(interface_name), item
                            )
                        if interface_name not in built_in_interfaces:
                            raise StructureException(
                                'Built-In interface {} does not exist.'.format(interface_name), item
                            )
                        global_ctx._interfaces[interface_name] = built_in_interfaces[interface_name].copy()  # noqa: E501
                else:
                    raise StructureException((
                        "Only built-in vyper.interfaces package supported for "
                        "`from` statement."
                    ), item)
            elif isinstance(item, ast.Import):
                for item_alias in item.names:
                    if not item_alias.asname:
                        raise StructureException(
                            'External interface import expects and alias using `as` statement', item
                        )

                    interface_name = item_alias.asname
                    if interface_name in global_ctx._interfaces:
                        raise StructureException(
                            'Duplicate import of {}'.format(interface_name), item
                        )
                    if interface_name not in interface_codes:
                        raise StructureException(
                            'Unknown interface {}'.format(interface_name), item
                        )
                    global_ctx._interfaces[interface_name] = extract_sigs(interface_codes[interface_name])  # noqa: E501
            else:
                raise StructureException("Invalid top-level statement", item)

        # Merge intefaces.
        if global_ctx._interfaces:
            for interface_name, sigs in global_ctx._interfaces.items():
                if interface_name in global_ctx._implemented_interfaces:
                    for func_sig in sigs:
                        setattr(func_sig, 'defined_in_interface', interface_name)
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
                o.append((
                    funname,
                    ("arg%d: int128, " % depth) + head,
                    ("[arg%d]" % depth) + tail,
                    base,
                ))
            return o
        # Mapping type: do not extend the getter name, add an input argument for
        # the key in the map, add a value access to the return statement
        elif isinstance(typ, MappingType):
            o = []
            for funname, head, tail, base in cls._mk_getter_helper(typ.valuetype, depth + 1):
                o.append((
                    funname,
                    ("arg%d: %r, " % (depth, typ.keytype)) + head,
                    ("[arg%d]" % depth) + tail,
                    base,
                ))
            return o
        # Struct type: for each member variable, make a separate getter, extend
        # its function name with the name of the variable, do not add input
        # arguments, add a member access to the return statement
        elif isinstance(typ, StructType):
            o = []
            for k, v in typ.members.items():
                for funname, head, tail, base in cls._mk_getter_helper(v, depth):
                    o.append(("__" + k + funname, head, "." + k + tail, base))
            return o
        else:
            raise Exception("Unexpected type")

    # Make a list of getters for a given variable name with a given type
    @classmethod
    def mk_getter(cls, varname, typ):
        funs = cls._mk_getter_helper(typ)
        return [
            """@public\n@constant\ndef %s%s(%s) -> %s: return self.%s%s""" % (
                varname, funname, head.rstrip(', '), base, varname, tail
            ) for (funname, head, tail, base) in funs
        ]

    # Parser for a single line
    @staticmethod
    def parse_line(code):
        parsed_ast = parse_to_ast(code)[0]
        return parsed_ast

    # A struct is a list of members
    def make_struct(self, name, body):
        members = []
        for item in body:
            if isinstance(item, ast.AnnAssign):
                member_name = item.target
                member_type = item.annotation
                # Check well-formedness of member names
                if not isinstance(member_name, ast.Name):
                    raise InvalidTypeException(
                        "Invalid member name for struct %r, needs to be a valid name. " % name,
                        item
                    )
                check_valid_varname(
                    member_name.id,
                    self._custom_units,
                    self._structs,
                    self._constants,
                    item,
                    "Invalid member name for struct. "
                )
                # Check well-formedness of member types
                # Note this kicks out mutually recursive structs,
                # raising an exception instead of stackoverflow.
                # A struct must be defined before it is referenced.
                # This feels like a semantic step and maybe should be pushed
                # to a later compilation stage.
                parse_type(
                    member_type,
                    'storage',
                    custom_units=self._custom_units,
                    custom_structs=self._structs,
                    constants=self._constants,
                )
                members.append((member_name, member_type))
            else:
                raise StructureException("Structs can only contain variables", item)
        return members

    # A contract is a list of functions.
    @staticmethod
    def make_contract(code):
        _defs = []
        for item in code:
            # Function definitions
            if isinstance(item, ast.FunctionDef):
                _defs.append(item)
            else:
                raise StructureException("Invalid contract reference", item)
        return _defs

    def get_item_name_and_attributes(self, item, attributes):
        is_map_invocation = (
            (
                isinstance(item, ast.Call) and isinstance(item.func, ast.Name)
            ) and item.func.id == 'map'
        )

        if isinstance(item, ast.Name):
            return item.id, attributes
        elif isinstance(item, ast.AnnAssign):
            return self.get_item_name_and_attributes(item.annotation, attributes)
        elif isinstance(item, ast.Subscript):
            return self.get_item_name_and_attributes(item.value, attributes)
        elif is_map_invocation:
            if len(item.args) != 2:
                raise StructureException(
                    "Map type expects two type arguments map(type1, type2)", item.func
                )
            return self.get_item_name_and_attributes(item.args, attributes)
        # elif ist
        elif isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
            attributes[item.func.id] = True
            # Raise for multiple args
            if len(item.args) != 1:
                raise StructureException("%s expects one arg (the type)" % item.func.id)
            return self.get_item_name_and_attributes(item.args[0], attributes)
        return None, attributes

    def is_valid_varname(self, name, item):
        """ Valid variable name, checked against global context. """
        check_valid_varname(name, self._custom_units, self._structs, self._constants, item)
        if name in self._globals:
            raise VariableDeclarationException(
                'Invalid name "%s", previously defined as global.' % name, item
            )
        return True

    def add_constant(self, item):
        args = item.annotation.args
        if not item.value:
            raise StructureException('Constants must express a value!', item)

        is_valid_struct = (
            len(args) == 1 and isinstance(args[0], (ast.Subscript, ast.Name, ast.Call))
        ) and item.target

        if is_valid_struct:
            c_name = item.target.id
            if self.is_valid_varname(c_name, item):
                self._constants[c_name] = self.unroll_constant(item)
        else:
            raise StructureException('Incorrectly formatted struct', item)

    @staticmethod
    def get_call_func_name(item):
        if isinstance(item.annotation, ast.Call) and \
           isinstance(item.annotation.func, ast.Name):
            return item.annotation.func.id

    def add_globals_and_events(self, item):
        item_attributes = {"public": False}

        if len(self._globals) > NONRENTRANT_STORAGE_OFFSET:
            raise ParserException(
                "Too many globals defined, only {} globals are allowed".format(
                    NONRENTRANT_STORAGE_OFFSET
                ),
                item,
            )

        # Make sure we have a valid variable name.
        if not isinstance(item.target, ast.Name):
            raise StructureException('Invalid global variable name', item.target)

        # Handle constants.
        if self.get_call_func_name(item) == "constant":
            self.   _constants.add_constant(item, global_ctx=self)
            return

        # Handle events.
        if not (self.get_call_func_name(item) == "event"):
            item_name, item_attributes = self.get_item_name_and_attributes(item, item_attributes)
            if not all([attr in valid_global_keywords for attr in item_attributes.keys()]):
                raise StructureException('Invalid global keyword used: %s' % item_attributes, item)

        if item.value is not None:
            raise StructureException('May not assign value whilst defining type', item)
        elif self.get_call_func_name(item) == "event":
            if self._globals or len(self._defs):
                raise EventDeclarationException(
                    "Events must all come before global declarations and function definitions", item
                )
            self._events.append(item)
        elif not isinstance(item.target, ast.Name):
            raise StructureException(
                "Can only assign type to variable in top-level statement", item
            )

        # Is this a custom unit definition.
        elif item.target.id == 'units':
            if not self._custom_units:
                if not isinstance(item.annotation, ast.Dict):
                    raise VariableDeclarationException(
                        "Define custom units using units: { }.", item.target
                    )
                for key, value in zip(item.annotation.keys, item.annotation.values):
                    if not isinstance(value, ast.Str):
                        raise VariableDeclarationException(
                            "Custom unit description must be a valid string", value
                        )
                    if not isinstance(key, ast.Name):
                        raise VariableDeclarationException(
                            "Custom unit name must be a valid string", key
                        )
                    check_valid_varname(
                        key.id,
                        self._custom_units,
                        self._structs,
                        self._constants,
                        key,
                        "Custom unit invalid."
                    )
                    self._custom_units.add(key.id)
                    self._custom_units_descriptions[key.id] = value.s
            else:
                raise VariableDeclarationException(
                    "Custom units can only be defined once", item.target
                )

        # Check if variable name is valid.
        # Don't move this check higher, as unit parsing has to happen first.
        elif not self.is_valid_varname(item.target.id, item):
            pass

        elif len(self._defs):
            raise StructureException(
                "Global variables must all come before function definitions",
                item,
            )

        elif item_name in self._contracts or item_name in self._interfaces:
            if self.get_call_func_name(item) == "address":
                raise StructureException(
                    f"Persistent address({item_name}) style contract declarations "
                    "are not support anymore."
                    f" Use {item.target.id}: {item_name} instead"
                )
            self._globals[item.target.id] = ContractRecord(
                item.target.id,
                len(self._globals),
                ContractType(item_name),
                True,
            )
            if item_attributes["public"]:
                typ = ContractType(item_name)
                for getter in self.mk_getter(item.target.id, typ):
                    self._getters.append(self.parse_line('\n' * (item.lineno - 1) + getter))
                    self._getters[-1].pos = getpos(item)
        elif self.get_call_func_name(item) == "public":
            if isinstance(item.annotation.args[0], ast.Name) and item_name in self._contracts:
                typ = ContractType(item_name)
            else:
                typ = parse_type(
                    item.annotation.args[0],
                    'storage',
                    custom_units=self._custom_units,
                    custom_structs=self._structs,
                    constants=self._constants,
                )
            self._globals[item.target.id] = VariableRecord(
                item.target.id,
                len(self._globals),
                typ,
                True,
            )
            # Adding getters here
            for getter in self.mk_getter(item.target.id, typ):
                self._getters.append(self.parse_line('\n' * (item.lineno - 1) + getter))
                self._getters[-1].pos = getpos(item)

        elif isinstance(item.annotation, (ast.Name, ast.Call, ast.Subscript)):
            self._globals[item.target.id] = VariableRecord(
                item.target.id, len(self._globals),
                parse_type(
                    item.annotation,
                    'storage',
                    custom_units=self._custom_units,
                    custom_structs=self._structs,
                    constants=self._constants
                ),
                True
            )
        else:
            raise InvalidTypeException('Invalid global type specified', item)

    def parse_type(self, ast_node, location):
        return parse_type(
            ast_node,
            location,
            sigs=self._contracts,
            custom_units=self._custom_units,
            custom_structs=self._structs,
            constants=self._constants
        )

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
