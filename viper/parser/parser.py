import ast

from viper.exceptions import (
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)
from viper.function_signature import (
    FunctionSignature,
    VariableRecord,
)
from viper.signatures.event_signature import (
    EventSignature
)
from viper.premade_contracts import (
    premade_contracts
)
from .stmt import Stmt
from .expr import Expr
from .parser_utils import LLLnode
from .parser_utils import (
    get_length,
    getpos,
    make_byte_array_copier,
    add_variable_offset,
    base_type_conversion,
    unwrap_location,
    byte_array_to_num,
)
from viper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    MappingType,
    NullType,
    StructType,
    TupleType,
)
from viper.types import (
    get_size_of_type,
    is_base_type,
    parse_type,
    ceil32
)
from viper.utils import (
    MemoryPositions,
    LOADED_LIMIT_MAP,
    reserved_words,
    string_to_bytes
)
from viper.utils import (
    bytes_to_int,
    calc_mem_gas,
    is_varname_valid,
)


if not hasattr(ast, 'AnnAssign'):
    raise Exception("Requires python 3.6 or higher for annotation support")


# Converts code to parse tree
def parse(code):
    o = ast.parse(code)
    decorate_ast_with_source(o, code)
    o = resolve_negative_literals(o)
    return o.body


# Parser for a single line
def parse_line(code):
    o = ast.parse(code).body[0]
    decorate_ast_with_source(o, code)
    o = resolve_negative_literals(o)
    return o


# Decorate every node of an AST tree with the original source code.
# This is necessary to facilitate error pretty-printing.
def decorate_ast_with_source(_ast, code):

    class MyVisitor(ast.NodeVisitor):
        def visit(self, node):
            self.generic_visit(node)
            node.source_code = code

    MyVisitor().visit(_ast)


def resolve_negative_literals(_ast):

    class RewriteUnaryOp(ast.NodeTransformer):
        def visit_UnaryOp(self, node):
            if isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Num):
                node.operand.n = 0 - node.operand.n
                return node.operand
            else:
                return node

    return RewriteUnaryOp().visit(_ast)


# Make a getter for a variable. This function gives an output that
# contains lists of 4-tuples:
# (i) the tail of the function name for the getter
# (ii) the code for the arguments that the function takes
# (iii) the code for the return
# (iv) the output type
#
# Here is an example:
#
# Input: my_variable: {foo: num, bar: decimal[5]}
#
# Output:
#
# [('__foo', '', '.foo', 'num'),
#  ('__bar', 'arg0: num, ', '.bar[arg0]', 'decimal')]
#
# The getters will have code:
# def get_my_variable__foo() -> num: return self.foo
# def get_my_variable__bar(arg0: nun) -> decimal: return self.bar[arg0]

def _mk_getter_helper(typ, depth=0):
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
        for funname, head, tail, base in _mk_getter_helper(typ.subtype, depth + 1):
            o.append((funname, ("arg%d: num, " % depth) + head, ("[arg%d]" % depth) + tail, base))
        return o
    # Mapping type: do not extend the getter name, add an input argument for
    # the key in the map, add a value access to the return statement
    elif isinstance(typ, MappingType):
        o = []
        for funname, head, tail, base in _mk_getter_helper(typ.valuetype, depth + 1):
            o.append((funname, ("arg%d: %r, " % (depth, typ.keytype)) + head, ("[arg%d]" % depth) + tail, base))
        return o
    # Struct type: for each member variable, make a separate getter, extend
    # its function name with the name of the variable, do not add input
    # arguments, add a member access to the return statement
    elif isinstance(typ, StructType):
        o = []
        for k, v in typ.members.items():
            for funname, head, tail, base in _mk_getter_helper(v, depth):
                o.append(("__" + k + funname, head, "." + k + tail, base))
        return o
    else:
        raise Exception("Unexpected type")


# Make a list of getters for a given variable name with a given type
def mk_getter(varname, typ):
    funs = _mk_getter_helper(typ)
    return ["""@public\n@constant\ndef get_%s%s(%s) -> %s: return self.%s%s""" % (varname, funname, head.rstrip(', '), base, varname, tail)
            for (funname, head, tail, base) in funs]


def add_contract(code):
    _defs = []
    for item in code:
        # Function definitions
        if isinstance(item, ast.FunctionDef):
            _defs.append(item)
        else:
            raise StructureException("Invalid contract reference", item)
    return _defs


def add_globals_and_events(_contracts, _defs, _events, _getters, _globals, item):
    if item.value is not None:
        raise StructureException('May not assign value whilst defining type', item)
    elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "__log__":
        if _globals or len(_defs):
            raise StructureException("Events must all come before global declarations and function definitions", item)
        _events.append(item)
    elif not isinstance(item.target, ast.Name):
        raise StructureException("Can only assign type to variable in top-level statement", item)
    # Check if variable name is reserved or invalid
    elif not is_varname_valid(item.target.id):
        raise VariableDeclarationException("Variable name invalid or reserved: ", item.target)
    # Check if global already exists, if so error
    elif item.target.id in _globals:
        raise VariableDeclarationException("Cannot declare a persistent variable twice!", item.target)
    elif len(_defs):
        raise StructureException("Global variables must all come before function definitions", item)
    # If the type declaration is of the form public(<type here>), then proceed with
    # the underlying type but also add getters
    elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "address":
        if len(item.annotation.args) != 1:
            raise StructureException("Address expects one arg (the type)")
        if item.annotation.args[0].id not in premade_contracts:
            raise VariableDeclarationException("Unsupported premade contract declaration", item.annotation.args[0])
        premade_contract = premade_contracts[item.annotation.args[0].id]
        _contracts[item.target.id] = add_contract(premade_contract.body)
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), BaseType('address'), True)
    elif isinstance(item, ast.AnnAssign) and isinstance(item.annotation, ast.Name) and item.annotation.id in _contracts:
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), BaseType('address', item.annotation.id), True)
    elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "public":
        if len(item.annotation.args) != 1:
            raise StructureException("Public expects one arg (the type)")
        if isinstance(item.annotation.args[0], ast.Name) and item.annotation.args[0].id in _contracts:
            typ = BaseType('address', item.annotation.args[0].id)
        else:
            typ = parse_type(item.annotation.args[0], 'storage')
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), typ, True)
        # Adding getters here
        for getter in mk_getter(item.target.id, typ):
            _getters.append(parse_line('\n' * (item.lineno - 1) + getter))
            _getters[-1].pos = getpos(item)
    else:
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), parse_type(item.annotation, 'storage'), True)
    return _contracts, _events, _globals, _getters


# Parse top-level functions and variables
def get_contracts_and_defs_and_globals(code):
    _contracts = {}
    _events = []
    _globals = {}
    _defs = []
    _getters = []
    for item in code:
        # Contract references
        if isinstance(item, ast.ClassDef):
            if _events or _globals or _defs:
                    raise StructureException("External contract declarations must come before event declarations, global declarations, and function definitions", item)
            _contracts[item.name] = add_contract(item.body)
        # Statements of the form:
        # variable_name: type
        elif isinstance(item, ast.AnnAssign):
            _contracts, _events, _globals, _getters = add_globals_and_events(_contracts, _defs, _events, _getters, _globals, item)
        # Function definitions
        elif isinstance(item, ast.FunctionDef):
            _defs.append(item)
        else:
            raise StructureException("Invalid top-level statement", item)
    return _contracts, _events, _defs + _getters, _globals


# Header code
initializer_list = ['seq', ['mstore', 28, ['calldataload', 0]]]
# Store limit constants at fixed addresses in memory.
initializer_list += [['mstore', pos, limit_size] for pos, limit_size in LOADED_LIMIT_MAP.items()]
initializer_lll = LLLnode.from_list(initializer_list, typ=None)


# Contains arguments, variables, etc
class Context():
    def __init__(self, vars=None, globals=None, sigs=None, forvars=None, return_type=None, is_constant=False, is_payable=False, origcode=''):
        # In-memory variables, in the form (name, memory location, type)
        self.vars = vars or {}
        self.next_mem = MemoryPositions.RESERVED_MEMORY
        # Global variables, in the form (name, storage location, type)
        self.globals = globals or {}
        # ABI objects, in the form {classname: ABI JSON}
        self.sigs = sigs or {}
        # Variables defined in for loops, eg. for i in range(6): ...
        self.forvars = forvars or {}
        # Return type of the function
        self.return_type = return_type
        # Is the function constant?
        self.is_constant = is_constant
        # Is the function payable?
        self.is_payable = is_payable
        # Number of placeholders generated (used to generate random names)
        self.placeholder_count = 1
        # Original code (for error pretty-printing purposes)
        self.origcode = origcode
        # In Loop status. Whether body is currently evaluating within a for-loop or not.
        self.in_for_loop = set()
        # Count returns in function
        self.function_return_count = 0
        # Current block scope
        self.blockscopes = set()

    def set_in_for_loop(self, name_of_list):
        self.in_for_loop.add(name_of_list)

    def remove_in_for_loop(self, name_of_list):
        self.in_for_loop.remove(name_of_list)

    def start_blockscope(self, blockscope_id):
        self.blockscopes.add(blockscope_id)

    def end_blockscope(self, blockscope_id):
        # Remove all variables that have specific blockscope_id attached.
        self.vars = {
            name: var_record for name, var_record in self.vars.items()
            if blockscope_id not in var_record.blockscopes
        }
        # Remove block scopes
        self.blockscopes.remove(blockscope_id)

    def increment_return_counter(self):
        self.function_return_count += 1

    # Add a new variable
    def new_variable(self, name, typ):
        if not is_varname_valid(name):
            raise VariableDeclarationException("Variable name invalid or reserved: " + name)
        if name in self.vars or name in self.globals:
            raise VariableDeclarationException("Duplicate variable name: %s" % name)
        self.vars[name] = VariableRecord(name, self.next_mem, typ, True, self.blockscopes.copy())
        pos = self.next_mem
        self.next_mem += 32 * get_size_of_type(typ)
        return pos

    # Add an anonymous variable (used in some complex function definitions)
    def new_placeholder(self, typ):
        name = '_placeholder_' + str(self.placeholder_count)
        self.placeholder_count += 1
        return self.new_variable(name, typ)

    # Get the next unused memory location
    def get_next_mem(self):
        return self.next_mem


# Is a function the initializer?
def is_initializer(code):
    return code.name == '__init__'


# Get ABI signature
def mk_full_signature(code):
    o = []
    _contracts, _events, _defs, _globals = get_contracts_and_defs_and_globals(code)
    for code in _events:
        sig = EventSignature.from_declaration(code)
        o.append(sig.to_abi_dict())
    for code in _defs:
        sig = FunctionSignature.from_definition(code, _contracts)
        if not sig.private:
            o.append(sig.to_abi_dict())
    return o


def parse_events(sigs, _events):
    for event in _events:
        sigs[event.target.id] = EventSignature.from_declaration(event)
    return sigs


def parse_external_contracts(external_contracts, _contracts):
    for _contractname in _contracts:
        _contract_defs = _contracts[_contractname]
        _defnames = [_def.name for _def in _contract_defs]
        contract = {}
        if len(set(_defnames)) < len(_contract_defs):
            raise VariableDeclarationException("Duplicate function name: %s" % [name for name in _defnames if _defnames.count(name) > 1][0])
        for _def in _contract_defs:
            sig = FunctionSignature.from_definition(_def)
            contract[sig.name] = sig
        external_contracts[_contractname] = contract
    return external_contracts


def parse_other_functions(o, otherfuncs, _globals, sigs, external_contracts, origcode, runtime_only=False):
    sub = ['seq', initializer_lll]
    add_gas = initializer_lll.gas
    for _def in otherfuncs:
        sub.append(parse_func(_def, _globals, {**{'self': sigs}, **external_contracts}, origcode))
        sub[-1].total_gas += add_gas
        add_gas += 30
        sig = FunctionSignature.from_definition(_def, external_contracts)
        sig.gas = sub[-1].total_gas
        sigs[sig.name] = sig
    if runtime_only:
        return sub
    else:
        o.append(['return', 0, ['lll', sub, 0]])
        return o


# Main python parse tree => LLL method
def parse_tree_to_lll(code, origcode, runtime_only=False):
    _contracts, _events, _defs, _globals = get_contracts_and_defs_and_globals(code)
    _names = [_def.name for _def in _defs] + [_event.target.id for _event in _events]
    # Checks for duplicate function / event names
    if len(set(_names)) < len(_names):
        raise VariableDeclarationException("Duplicate function or event name: %s" % [name for name in _names if _names.count(name) > 1][0])
    # Initialization function
    initfunc = [_def for _def in _defs if is_initializer(_def)]
    # Regular functions
    otherfuncs = [_def for _def in _defs if not is_initializer(_def)]
    sigs = {}
    external_contracts = {}
    # Create the main statement
    o = ['seq']
    if _events:
        sigs = parse_events(sigs, _events)
    if _contracts:
        external_contracts = parse_external_contracts(external_contracts, _contracts)
    # If there is an init func...
    if initfunc:
        o.append(['seq', initializer_lll])
        o.append(parse_func(initfunc[0], _globals, {**{'self': sigs}, **external_contracts}, origcode))
    # If there are regular functions...
    if otherfuncs:
        o = parse_other_functions(o, otherfuncs, _globals, sigs, external_contracts, origcode, runtime_only)
    return LLLnode.from_list(o, typ=None)


# Checks that an input matches its type
def make_clamper(datapos, mempos, typ, is_init=False):
    if not is_init:
        data_decl = ['calldataload', ['add', 4, datapos]]
        copier = lambda pos, sz: ['calldatacopy', mempos, ['add', 4, pos], sz]
    else:
        data_decl = ['codeload', ['add', '~codelen', datapos]]
        copier = lambda pos, sz: ['codecopy', mempos, ['add', '~codelen', pos], sz]
    # Numbers: make sure they're in range
    if is_base_type(typ, 'num'):
        return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINNUM], data_decl, ['mload', MemoryPositions.MAXNUM]],
                                 typ=typ, annotation='checking num input')
    # Booleans: make sure they're zero or one
    elif is_base_type(typ, 'bool'):
        return LLLnode.from_list(['uclamplt', data_decl, 2], typ=typ, annotation='checking bool input')
    # Addresses: make sure they're in range
    elif is_base_type(typ, 'address'):
        return LLLnode.from_list(['uclamplt', data_decl, ['mload', MemoryPositions.ADDRSIZE]], typ=typ, annotation='checking address input')
    # Bytes: make sure they have the right size
    elif isinstance(typ, ByteArrayType):
        return LLLnode.from_list(['seq',
                                    copier(data_decl, 32 + typ.maxlen),
                                    ['assert', ['le', ['calldataload', ['add', 4, data_decl]], typ.maxlen]]],
                                 typ=None, annotation='checking bytearray input')
    # Lists: recurse
    elif isinstance(typ, ListType):
        o = []
        for i in range(typ.count):
            offset = get_size_of_type(typ.subtype) * 32 * i
            o.append(make_clamper(datapos + offset, mempos + offset, typ.subtype, is_init))
        return LLLnode.from_list(['seq'] + o, typ=None, annotation='checking list input')
    # Otherwise don't make any checks
    else:
        return LLLnode.from_list('pass')


# Parses a function declaration
def parse_func(code, _globals, sigs, origcode, _vars=None):
    if _vars is None:
        _vars = {}
    sig = FunctionSignature.from_definition(code, sigs)
    # Check for duplicate variables with globals
    for arg in sig.args:
        if arg.name in _globals:
            raise VariableDeclarationException("Variable name duplicated between function arguments and globals: " + arg.name)
    # Create a context
    context = Context(vars=_vars, globals=_globals, sigs=sigs,
                      return_type=sig.output_type, is_constant=sig.const, is_payable=sig.payable, origcode=origcode)
    # Copy calldata to memory for fixed-size arguments
    copy_size = sum([32 if isinstance(arg.typ, ByteArrayType) else get_size_of_type(arg.typ) * 32 for arg in sig.args])
    context.next_mem += copy_size
    if not len(sig.args):
        copier = 'pass'
    elif sig.name == '__init__':
        copier = ['codecopy', MemoryPositions.RESERVED_MEMORY, '~codelen', copy_size]
    else:
        copier = ['calldatacopy', MemoryPositions.RESERVED_MEMORY, 4, copy_size]
    clampers = [copier]
    # Add asserts for payable and internal
    if not sig.payable:
        clampers.append(['assert', ['iszero', 'callvalue']])
    if sig.private:
        clampers.append(['assert', ['eq', 'caller', 'address']])
    # Fill in variable positions
    for arg in sig.args:
        clampers.append(make_clamper(arg.pos, context.next_mem, arg.typ, sig.name == '__init__'))
        if isinstance(arg.typ, ByteArrayType):
            context.vars[arg.name] = VariableRecord(arg.name, context.next_mem, arg.typ, False)
            context.next_mem += 32 * get_size_of_type(arg.typ)
        else:
            context.vars[arg.name] = VariableRecord(arg.name, MemoryPositions.RESERVED_MEMORY + arg.pos, arg.typ, False)
    # Create "clampers" (input well-formedness checkers)
    # Return function body
    if sig.name == '__init__':
        o = LLLnode.from_list(['seq'] + clampers + [parse_body(code.body, context)], pos=getpos(code))
    else:
        method_id_node = LLLnode.from_list(sig.method_id, pos=getpos(code), annotation='%s' % sig.name)
        o = LLLnode.from_list(['if',
                                  ['eq', ['mload', 0], method_id_node],
                                  ['seq'] + clampers + [parse_body(c, context) for c in code.body] + ['stop']
                               ], typ=None, pos=getpos(code))

    # Check for at leasts one return statement if necessary.
    if context.return_type and context.function_return_count == 0:
        raise StructureException(
            "Missing return statement in function '%s' " % sig.name, code
        )

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(o.context.next_mem)
    o.func_name = sig.name
    return o


# Parse a piece of code
def parse_body(code, context):
    if not isinstance(code, list):
        return parse_stmt(code, context)
    o = []
    for stmt in code:
        o.append(parse_stmt(stmt, context))
    return LLLnode.from_list(['seq'] + o, pos=getpos(code[0]) if code else None)


def external_contract_call_stmt(stmt, context, contract_name, contract_address):
    if contract_name not in context.sigs:
        raise VariableDeclarationException("Contract not declared yet: %s" % contract_name)
    method_name = stmt.func.attr
    if method_name not in context.sigs[contract_name]:
        raise VariableDeclarationException("Function not declared yet: %s (reminder: "
                                                    "function must be declared in the correct contract)" % method_name)
    sig = context.sigs[contract_name][method_name]
    inargs, inargsize = pack_arguments(sig, [parse_expr(arg, context) for arg in stmt.args], context)
    sub = ['seq', ['assert', ['extcodesize', contract_address]],
                    ['assert', ['ne', 'address', contract_address]]]
    if context.is_constant:
        sub.append(['assert', ['staticcall', 'gas', contract_address, inargs, inargsize, 0, 0]])
    else:
        sub.append(['assert', ['call', 'gas', contract_address, 0, inargs, inargsize, 0, 0]])
    o = LLLnode.from_list(sub, typ=sig.output_type, location='memory', pos=getpos(stmt))
    return o


def external_contract_call_expr(expr, context, contract_name, contract_address):
    if contract_name not in context.sigs:
        raise VariableDeclarationException("Contract not declared yet: %s" % contract_name)
    method_name = expr.func.attr
    if method_name not in context.sigs[contract_name]:
        raise VariableDeclarationException("Function not declared yet: %s (reminder: "
                                                    "function must be declared in the correct contract)" % method_name)
    sig = context.sigs[contract_name][method_name]
    inargs, inargsize = pack_arguments(sig, [parse_expr(arg, context) for arg in expr.args], context)
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    if isinstance(sig.output_type, BaseType):
        returner = output_placeholder
    elif isinstance(sig.output_type, ByteArrayType):
        returner = output_placeholder + 32
    else:
        raise TypeMismatchException("Invalid output type: %r" % sig.output_type, expr)
    sub = ['seq', ['assert', ['extcodesize', contract_address]],
                    ['assert', ['ne', 'address', contract_address]]]
    if context.is_constant:
        sub.append(['assert', ['staticcall', 'gas', contract_address, inargs, inargsize,
                    output_placeholder, get_size_of_type(sig.output_type) * 32]])
    else:
        sub.append(['assert', ['call', 'gas', contract_address, 0, inargs, inargsize,
            output_placeholder, get_size_of_type(sig.output_type) * 32]])
    sub.extend([0, returner])
    o = LLLnode.from_list(sub, typ=sig.output_type, location='memory', pos=getpos(expr))
    return o


# Parse an expression
def parse_expr(expr, context):
    return Expr(expr, context).lll_node


# Create an x=y statement, where the types may be compound
def make_setter(left, right, location, pos=None):
    # Basic types
    if isinstance(left.typ, BaseType):
        right = base_type_conversion(right, right.typ, left.typ, pos)
        if location == 'storage':
            return LLLnode.from_list(['sstore', left, right], typ=None)
        elif location == 'memory':
            return LLLnode.from_list(['mstore', left, right], typ=None)
    # Byte arrays
    elif isinstance(left.typ, ByteArrayType):
        return make_byte_array_copier(left, right)
    # Can't copy mappings
    elif isinstance(left.typ, MappingType):
        raise TypeMismatchException("Cannot copy mappings; can only copy individual elements", pos)
    # Arrays
    elif isinstance(left.typ, ListType):
        # Cannot do something like [a, b, c] = [1, 2, 3]
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, (ListType, NullType)):
            raise TypeMismatchException("Setter type mismatch: left side is array, right side is %r" % right.typ, pos)
        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        # Type checks
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, ListType):
                raise TypeMismatchException("Left side is array, right side is not", pos)
            if left.typ.count != right.typ.count:
                raise TypeMismatchException("Mismatched number of elements", pos)
        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != left.typ.count:
                raise TypeMismatchException("Mismatched number of elements", pos)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        right.args[i], location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        LLLnode.from_list(None, typ=NullType()), location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        add_variable_offset(right_token, LLLnode.from_list(i, typ='num')), location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['with', '_R', right, ['seq'] + subs]], typ=None)
    # Structs
    elif isinstance(left.typ, (StructType, TupleType)):
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, left.typ.__class__):
                raise TypeMismatchException("Setter type mismatch: left side is %r, right side is %r" % (left.typ, right.typ), pos)
            if isinstance(left.typ, StructType):
                for k in left.typ.members:
                    if k not in right.typ.members:
                        raise TypeMismatchException("Keys don't match for structs, missing %s" % k, pos)
                for k in right.typ.members:
                    if k not in left.typ.members:
                        raise TypeMismatchException("Keys don't match for structs, extra %s" % k, pos)
            else:
                if len(left.typ.members) != len(right.typ.members):
                    raise TypeMismatchException("Tuple lengths don't match, %d vs %d" % (len(left.typ.members), len(right.typ.members)), pos)
        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        if isinstance(left.typ, StructType):
            keyz = sorted(list(left.typ.members.keys()))
        else:
            keyz = list(range(len(left.typ.members)))
        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != len(keyz):
                raise TypeMismatchException("Mismatched number of elements", pos)
            subs = []
            for i, typ in enumerate(keyz):
                subs.append(make_setter(add_variable_offset(left_token, typ), right.args[i], location))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for typ in keyz:
                subs.append(make_setter(add_variable_offset(left_token, typ), LLLnode.from_list(None, typ=NullType()), location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            subs = []
            for typ in keyz:
                subs.append(make_setter(add_variable_offset(left_token, typ), add_variable_offset(right_token, typ), location, pos=pos))
            return LLLnode.from_list(['with', '_L', left, ['with', '_R', right, ['seq'] + subs]], typ=None)
    else:
        raise Exception("Invalid type for setters")


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


def pack_logging_topics(event_id, args, expected_topics, context):
    topics = [event_id]
    for pos, expected_topic in enumerate(expected_topics):
        typ = expected_topic.typ
        arg = args[pos]
        value = parse_expr(arg, context)
        if isinstance(typ, ByteArrayType) and (isinstance(arg, ast.Str) or (isinstance(arg, ast.Name) and arg.id not in reserved_words)):
            if value.typ.maxlen > typ.maxlen:
                raise TypeMismatchException("Topic input bytes are to big: %r %r" % (value.typ, typ))
            if isinstance(arg, ast.Str):
                bytez, bytez_length = string_to_bytes(arg.s)
                if len(bytez) > 32:
                    raise InvalidLiteralException("Can only log a maximum of 32 bytes at a time.")
                topics.append(bytes_to_int(bytez + b'\x00' * (32 - bytez_length)))
            else:
                size = context.vars[arg.id].size
                topics.append(byte_array_to_num(value, arg, 'num256', size))
        else:
            value = unwrap_location(value)
            value = base_type_conversion(value, value.typ, typ)
            topics.append(value)
    return topics


def pack_args_by_32(holder, maxlen, arg, typ, context, placeholder, dynamic_offset_counter=None, datamem_start=None):
    """
    Copy necessary variables to pre-allocated memory section.

    :param holder: Complete holder for all args
    :param maxlen: Total length in bytes of the full arg section (static + dynamic).
    :param arg: Current arg to pack
    :param context: Context of arg
    :param placeholder: Static placeholder for static argument part.
    :param dynamic_offset_counter: position counter stored in static args.
    :param dynamic_placeholder: pointer to current position in memory to write dynamic values to.
    :param datamem_start: position where the whole datemem section starts.
    """

    if isinstance(typ, BaseType):
        value = parse_expr(arg, context)
        value = base_type_conversion(value, value.typ, typ)
        holder.append(LLLnode.from_list(['mstore', placeholder, value], typ=typ, location='memory'))
    elif isinstance(typ, ByteArrayType):
        bytez = b''

        source_expr = Expr(arg, context)
        if isinstance(arg, ast.Str):
            if len(arg.s) > typ.maxlen:
                raise TypeMismatchException("Data input bytes are to big: %r %r" % (len(arg.s), typ))
            for c in arg.s:
                if ord(c) >= 256:
                    raise InvalidLiteralException("Cannot insert special character %r into byte array" % c)
                bytez += bytes([ord(c)])

            holder.append(source_expr.lll_node)

        # Set static offset, in arg slot.
        holder.append(LLLnode.from_list(['mstore', placeholder, ['mload', dynamic_offset_counter]]))
        # Get the biginning to write the ByteArray to.
        dest_placeholder = LLLnode.from_list(
            ['add', datamem_start, ['mload', dynamic_offset_counter]],
            typ=typ, location='memory', annotation="pack_args_by_32:dest_placeholder")
        copier = make_byte_array_copier(dest_placeholder, source_expr.lll_node)
        holder.append(copier)
        # Increment offset counter.
        increment_counter = LLLnode.from_list(
            ['mstore', dynamic_offset_counter,
                ['add', ['add', ['mload', dynamic_offset_counter], ['ceil32', ['mload', dest_placeholder]]], 32]]
        )
        holder.append(increment_counter)
    elif isinstance(typ, ListType):
        maxlen += (typ.count - 1) * 32
        typ = typ.subtype

        def check_list_type_match(provided):  # Check list types match.
            if provided != typ:
                raise TypeMismatchException(
                    "Log list type '%s' does not match provided, expected '%s'" % (provided, typ)
                )

        # List from storage
        if isinstance(arg, ast.Attribute) and arg.value.id == 'self':
            stor_list = context.globals[arg.attr]
            check_list_type_match(stor_list.typ.subtype)
            size = stor_list.typ.count
            for offset in range(0, size):
                arg2 = LLLnode.from_list(['sload', ['add', ['sha3_32', Expr(arg, context).lll_node], offset]],
                                         typ=typ)
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, context.new_placeholder(BaseType(32)))
        # List from variable.
        elif isinstance(arg, ast.Name):
            size = context.vars[arg.id].size
            pos = context.vars[arg.id].pos
            check_list_type_match(context.vars[arg.id].typ.subtype)
            for i in range(0, size):
                offset = 32 * i
                arg2 = LLLnode.from_list(pos + offset, typ=typ, location='memory')
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, context.new_placeholder(BaseType(32)))
        # is list literal.
        else:
            holder, maxlen = pack_args_by_32(holder, maxlen, arg.elts[0], typ, context, placeholder)
            for j, arg2 in enumerate(arg.elts[1:]):
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, context.new_placeholder(BaseType(32)))

    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(expected_data, args, context):
    # Checks to see if there's any data
    if not args:
        return ['seq'], 0, None, 0
    holder = ['seq']
    maxlen = len(args) * 32  # total size of all packed args (upper limit)
    dynamic_offset_counter = context.new_placeholder(BaseType(32))
    dynamic_placeholder = context.new_placeholder(BaseType(32))

    # Populate static placeholders.
    placeholder_map = {}
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        placeholder = context.new_placeholder(BaseType(32))
        placeholder_map[i] = placeholder
        if not isinstance(typ, ByteArrayType):
            holder, maxlen = pack_args_by_32(holder, maxlen, arg, typ, context, placeholder)

    # Dynamic position starts right after the static args.
    holder.append(LLLnode.from_list(['mstore', dynamic_offset_counter, maxlen]))

    # Calculate maximum dynamic offset placeholders, used for gas estimation.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        if isinstance(typ, ByteArrayType):
            maxlen += 32 + ceil32(typ.maxlen)

    # Obtain the start of the arg section.
    if isinstance(expected_data[0].typ, ListType):
        datamem_start = holder[1].to_list()[1][0]
    else:
        datamem_start = dynamic_placeholder + 32

    # Copy necessary data into allocated dynamic section.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        pack_args_by_32(
            holder=holder,
            maxlen=maxlen,
            arg=arg,
            typ=typ,
            context=context,
            placeholder=placeholder_map[i],
            datamem_start=datamem_start,
            dynamic_offset_counter=dynamic_offset_counter
        )

    return holder, maxlen, dynamic_offset_counter, datamem_start


# Pack function arguments for a call
def pack_arguments(signature, args, context):
    placeholder_typ = ByteArrayType(maxlen=sum([get_size_of_type(arg.typ) for arg in signature.args]) * 32 + 32)
    placeholder = context.new_placeholder(placeholder_typ)
    setters = [['mstore', placeholder, signature.method_id]]
    needpos = False
    staticarray_offset = 0
    expected_arg_count = len(signature.args)
    actual_arg_count = len(args)
    if actual_arg_count != expected_arg_count:
        raise StructureException("Wrong number of args for: %s (%s args, expected %s)" % (signature.name, actual_arg_count, expected_arg_count))

    for i, (arg, typ) in enumerate(zip(args, [arg.typ for arg in signature.args])):
        if isinstance(typ, BaseType):
            setters.append(make_setter(LLLnode.from_list(placeholder + staticarray_offset + 32 + i * 32, typ=typ), arg, 'memory'))
        elif isinstance(typ, ByteArrayType):
            setters.append(['mstore', placeholder + staticarray_offset + 32 + i * 32, '_poz'])
            arg_copy = LLLnode.from_list('_s', typ=arg.typ, location=arg.location)
            target = LLLnode.from_list(['add', placeholder + 32, '_poz'], typ=typ, location='memory')
            setters.append(['with', '_s', arg, ['seq',
                                                    make_byte_array_copier(target, arg_copy),
                                                    ['set', '_poz', ['add', 32, ['add', '_poz', get_length(arg_copy)]]]]])
            needpos = True
        elif isinstance(typ, ListType):
            target = LLLnode.from_list([placeholder + 32 + staticarray_offset + i * 32], typ=typ, location='memory')
            setters.append(make_setter(target, arg, 'memory'))
            staticarray_offset += 32 * (typ.count - 1)
        else:
            raise TypeMismatchException("Cannot pack argument of type %r" % typ)
    if needpos:
        return LLLnode.from_list(['with', '_poz', len(args) * 32 + staticarray_offset, ['seq'] + setters + [placeholder + 28]],
                                 typ=placeholder_typ, location='memory'), \
            placeholder_typ.maxlen - 28
    else:
        return LLLnode.from_list(['seq'] + setters + [placeholder + 28], typ=placeholder_typ, location='memory'), \
            placeholder_typ.maxlen - 28


def parse_to_lll(kode):
    code = parse(kode)
    return parse_tree_to_lll(code, kode)
