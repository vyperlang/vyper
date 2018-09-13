import ast

from vyper.exceptions import (
    EventDeclarationException,
    FunctionDeclarationException,
    StructureException,
    VariableDeclarationException,
)
from vyper.utils import (
    valid_global_keywords,
    is_varname_valid
)
from vyper.premade_contracts import (
    premade_contracts,
)
from vyper.parser.parser_utils import (
    decorate_ast_with_source,
    getpos,
    resolve_negative_literals,
)
from vyper.signatures.function_signature import (
    ContractRecord,
    VariableRecord
)
from vyper.types import (
    parse_type,
    ContractType,
    ByteArrayType,
    ListType,
    MappingType,
    StructType,
    BaseType,
)


# Datatype to store all global context information.
class GlobalContext:

    def __init__(self):
        self._contracts = dict()
        self._events = list()
        self._globals = dict()
        self._defs = list()
        self._getters = list()
        self._custom_units = list()
        self.constants = dict()

    # Parse top-level functions and variables
    @classmethod
    def get_global_context(cls, code):
        global_ctx = cls()

        for item in code:
            # Contract references
            if isinstance(item, ast.ClassDef):
                if global_ctx._events or global_ctx._globals or global_ctx._defs:
                    raise StructureException("External contract declarations must come before event declarations, global declarations, and function definitions", item)
                global_ctx._contracts[item.name] = global_ctx.add_contract(item.body)
            # Statements of the form:
            # variable_name: type
            elif isinstance(item, ast.AnnAssign):
                global_ctx.add_globals_and_events(item)
            # Function definitions
            elif isinstance(item, ast.FunctionDef):
                if item.name in global_ctx._globals:
                    raise FunctionDeclarationException("Function name shadowing a variable name: %s" % item.name)
                global_ctx._defs.append(item)
            else:
                raise StructureException("Invalid top-level statement", item)
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
        if isinstance(typ, BaseType):
            return [("", "", "", repr(typ))]
        elif isinstance(typ, ByteArrayType):
            return [("", "", "", repr(typ))]
        # List type: do not extend the getter name, add an input argument for
        # the index in the list, add an item access to the return statement
        elif isinstance(typ, ListType):
            o = []
            for funname, head, tail, base in cls._mk_getter_helper(typ.subtype, depth + 1):
                o.append((funname, ("arg%d: int128, " % depth) + head, ("[arg%d]" % depth) + tail, base))
            return o
        # Mapping type: do not extend the getter name, add an input argument for
        # the key in the map, add a value access to the return statement
        elif isinstance(typ, MappingType):
            o = []
            for funname, head, tail, base in cls._mk_getter_helper(typ.valuetype, depth + 1):
                o.append((funname, ("arg%d: %r, " % (depth, typ.keytype)) + head, ("[arg%d]" % depth) + tail, base))
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
        return ["""@public\n@constant\ndef %s%s(%s) -> %s: return self.%s%s""" % (varname, funname, head.rstrip(', '), base, varname, tail)
                for (funname, head, tail, base) in funs]

    # Parser for a single line
    @staticmethod
    def parse_line(code):
        o = ast.parse(code).body[0]
        decorate_ast_with_source(o, code)
        o = resolve_negative_literals(o)
        return o

    @staticmethod
    def add_contract(code):
        _defs = []
        for item in code:
            # Function definitions
            if isinstance(item, ast.FunctionDef):
                _defs.append(item)
            else:
                raise StructureException("Invalid contract reference", item)
        return _defs

    def get_item_name_and_attributes(self, item, attributes):
        if isinstance(item, ast.Name):
            return item.id, attributes
        elif isinstance(item, ast.AnnAssign):
            return self.get_item_name_and_attributes(item.annotation, attributes)
        elif isinstance(item, ast.Subscript):
            return self.get_item_name_and_attributes(item.value, attributes)
        # elif ist
        elif isinstance(item, ast.Call):
            attributes[item.func.id] = True
            # Raise for multiple args
            if len(item.args) != 1:
                raise StructureException("%s expects one arg (the type)" % item.func.id)
            return self.get_item_name_and_attributes(item.args[0], attributes)
        return None, attributes

    def add_globals_and_events(self, item):
        item_attributes = {"public": False}
        if not (isinstance(item.annotation, ast.Call) and item.annotation.func.id == "event"):
            item_name, item_attributes = self.get_item_name_and_attributes(item, item_attributes)
            if not all([attr in valid_global_keywords for attr in item_attributes.keys()]):
                raise StructureException('Invalid global keyword used: %s' % item_attributes, item)
        if item.value is not None:
            raise StructureException('May not assign value whilst defining type', item)
        elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "event":
            if self._globals or len(self._defs):
                raise EventDeclarationException("Events must all come before global declarations and function definitions", item)
            self._events.append(item)
        elif not isinstance(item.target, ast.Name):
            raise StructureException("Can only assign type to variable in top-level statement", item)

        # Is this a custom unit definition.
        elif item.target.id == 'units':
            if not self._custom_units:
                if not isinstance(item.annotation, ast.Dict):
                    raise VariableDeclarationException("Define custom units using units: { }.", item.target)
                for key, value in zip(item.annotation.keys, item.annotation.values):
                    if not isinstance(value, ast.Str):
                        raise VariableDeclarationException("Custom unit description must be a valid string.", value)
                    if not isinstance(key, ast.Name):
                        raise VariableDeclarationException("Custom unit name must be a valid string unquoted string.", key)
                    if key.id in self._custom_units:
                        raise VariableDeclarationException("Custom unit may only be defined once", key)
                    if not is_varname_valid(key.id, custom_units=self._custom_units):
                        raise VariableDeclarationException("Custom unit may not be a reserved keyword", key)
                    self._custom_units.append(key.id)
            else:
                raise VariableDeclarationException("Can units can only defined once.", item.target)

        # Check if variable name is reserved or invalid
        elif not is_varname_valid(item.target.id, custom_units=self._custom_units):
            raise VariableDeclarationException("Variable name invalid or reserved: ", item.target)

        # Check if global already exists, if so error
        elif item.target.id in self._globals:
            raise VariableDeclarationException("Cannot declare a persistent variable twice!", item.target)

        elif len(self._defs):
            raise StructureException("Global variables must all come before function definitions", item)

        # If the type declaration is of the form public(<type here>), then proceed with
        # the underlying type but also add getters
        elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "address":
            if item.annotation.args[0].id not in premade_contracts:
                raise VariableDeclarationException("Unsupported premade contract declaration", item.annotation.args[0])
            premade_contract = premade_contracts[item.annotation.args[0].id]
            self._contracts[item.target.id] = self.add_contract(premade_contract.body)
            self._globals[item.target.id] = VariableRecord(item.target.id, len(self._globals), BaseType('address'), True)

        elif item_name in self._contracts:
            self._globals[item.target.id] = ContractRecord(item.target.id, len(self._globals), ContractType(item_name), True)
            if item_attributes["public"]:
                typ = ContractType(item_name)
                for getter in self.mk_getter(item.target.id, typ):
                    self._getters.append(self.parse_line('\n' * (item.lineno - 1) + getter))
                    self._getters[-1].pos = getpos(item)

        elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "public":
            if isinstance(item.annotation.args[0], ast.Name) and item_name in self._contracts:
                typ = ContractType(item_name)
            else:
                typ = parse_type(item.annotation.args[0], 'storage', custom_units=self._custom_units)
            self._globals[item.target.id] = VariableRecord(item.target.id, len(self._globals), typ, True)
            # Adding getters here
            for getter in self.mk_getter(item.target.id, typ):
                self._getters.append(self.parse_line('\n' * (item.lineno - 1) + getter))
                self._getters[-1].pos = getpos(item)

        else:
            self._globals[item.target.id] = VariableRecord(
                item.target.id, len(self._globals),
                parse_type(item.annotation, 'storage', custom_units=self._custom_units),
                True
            )
