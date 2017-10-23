import ast

from viper.exceptions import (
    InvalidLiteralException,
    NonPayableViolationException,
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
from viper.functions import (
    dispatch_table,
)
from .stmt import Stmt
from .parser_utils import LLLnode
from .parser_utils import (
    get_length,
    get_number_as_fraction,
    get_original_if_0x_prefixed,
    getpos,
    make_byte_array_copier,
    add_variable_offset,
    base_type_conversion,
    unwrap_location
)
from viper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    MappingType,
    MixedType,
    NullType,
    StructType,
    TupleType,
)
from viper.types import (
    get_size_of_type,
    is_base_type,
    is_numeric_type,
    parse_type,
)
from viper.types import (
    are_units_compatible,
    combine_units,
)
from viper.utils import (
    DECIMAL_DIVISOR,
    MemoryPositions,
    LOADED_LIMIT_MAP
)
from viper.utils import (
    bytes_to_int,
    checksum_encode,
    calc_mem_gas,
    is_varname_valid,
)


if not hasattr(ast, 'AnnAssign'):
    raise Exception("Requires python 3.6 or higher for annotation support")


# Converts code to parse tree
def parse(code):
    o = ast.parse(code)
    decorate_ast_with_source(o, code)
    return o.body


# Parser for a single line
def parse_line(code):
    o = ast.parse(code).body[0]
    decorate_ast_with_source(o, code)
    return o


# Decorate every node of an AST tree with the original source code.
# This is necessary to facilitate error pretty-printing.
def decorate_ast_with_source(_ast, code):

    class MyVisitor(ast.NodeVisitor):
        def visit(self, node):
            self.generic_visit(node)
            node.source_code = code

    MyVisitor().visit(_ast)


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
    return ['@constant\ndef get_%s%s(%s) -> %s: return self.%s%s' % (varname, funname, head.rstrip(', '), base, varname, tail)
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


def add_globals_and_events(_defs, _events, _getters, _globals, item):
    if isinstance(item.annotation, ast.Call) and item.annotation.func.id == "__log__":
        if _globals or len(_defs):
            raise StructureException("Events must all come before global declarations and function definitions", item)
        _events.append(item)
    elif not isinstance(item.target, ast.Name):
        raise StructureException("Can only assign type to variable in top-level statement", item)
    # Check if global already exists, if so error
    elif item.target.id in _globals:
        raise VariableDeclarationException("Cannot declare a persistent variable twice!", item.target)
    elif len(_defs):
        raise StructureException("Global variables must all come before function definitions", item)
    # If the type declaration is of the form public(<type here>), then proceed with
    # the underlying type but also add getters
    elif isinstance(item.annotation, ast.Call) and item.annotation.func.id == "public":
        if len(item.annotation.args) != 1:
            raise StructureException("Public expects one arg (the type)")
        typ = parse_type(item.annotation.args[0], 'storage')
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), typ, True)
        # Adding getters here
        for getter in mk_getter(item.target.id, typ):
            _getters.append(parse_line('\n' * (item.lineno - 1) + getter))
            _getters[-1].pos = getpos(item)
    else:
        _globals[item.target.id] = VariableRecord(item.target.id, len(_globals), parse_type(item.annotation, 'storage'), True)
    return _events, _globals, _getters


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
            _events, _globals, _getters = add_globals_and_events(_defs, _events, _getters, _globals, item)
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

    # Add a new variable
    def new_variable(self, name, typ):
        if not is_varname_valid(name):
            raise VariableDeclarationException("Variable name invalid or reserved: " + name)
        if name in self.vars or name in self.globals:
            raise VariableDeclarationException("Duplicate variable name: %s" % name)
        self.vars[name] = VariableRecord(name, self.next_mem, typ, True)
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
        sig = FunctionSignature.from_definition(code)
        if not sig.internal:
            o.append(sig.to_abi_dict())
    return o


# Main python parse tree => LLL method
def parse_tree_to_lll(code, origcode):
    _contracts, _events, _defs, _globals = get_contracts_and_defs_and_globals(code)
    _names = [_def.name for _def in _defs] + [_event.target.id for _event in _events]
    # Checks for duplicate funciton / event names
    if len(set(_names)) < len(_names):
        raise VariableDeclarationException("Duplicate function or event name: %s" % [name for name in _names if _names.count(name) > 1][0])
    contracts = {}
    # Create the main statement
    o = ['seq']
    # Initialization function
    initfunc = [_def for _def in _defs if is_initializer(_def)]
    # Regular functions
    otherfuncs = [_def for _def in _defs if not is_initializer(_def)]
    sigs = {}
    if _events:
        for event in _events:
            sigs[event.target.id] = EventSignature.from_declaration(event)
    for _contractname in _contracts:
        _c_defs = _contracts[_contractname]
        _defnames = [_def.name for _def in _c_defs]
        contract = {}
        if len(set(_defnames)) < len(_c_defs):
            raise VariableDeclarationException("Duplicate function name: %s" % [name for name in _defnames if _defnames.count(name) > 1][0])
        c_otherfuncs = [_def for _def in _c_defs if not is_initializer(_def)]
        if c_otherfuncs:
            for _def in c_otherfuncs:
                sig = FunctionSignature.from_definition(_def)
                contract[sig.name] = sig
        contracts[_contractname] = contract
    _defnames = [_def.name for _def in _defs]
    if len(set(_defnames)) < len(_defs):
        raise VariableDeclarationException("Duplicate function name: %s" % [name for name in _defnames if _defnames.count(name) > 1][0])
    # If there is an init func...
    if initfunc:
        o.append(['seq', initializer_lll])
        o.append(parse_func(initfunc[0], _globals, {**{'self': sigs}, **contracts}, origcode))
    # If there are regular functions...
    if otherfuncs:
        sub = ['seq', initializer_lll]
        add_gas = initializer_lll.gas
        for _def in otherfuncs:
            sub.append(parse_func(_def, _globals, {**{'self': sigs}, **contracts}, origcode))
            sub[-1].total_gas += add_gas
            add_gas += 30
            sig = FunctionSignature.from_definition(_def)
            sig.gas = sub[-1].total_gas
            sigs[sig.name] = sig
        o.append(['return', 0, ['lll', sub, 0]])
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

    sig = FunctionSignature.from_definition(code)
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
    if sig.internal:
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


def external_contract_call_stmt(stmt, context):
    contract_name = stmt.func.value.func.id
    if contract_name not in context.sigs:
        raise VariableDeclarationException("Contract not declared yet: %s" % contract_name)
    method_name = stmt.func.attr
    if method_name not in context.sigs[contract_name]:
        raise VariableDeclarationException("Function not declared yet: %s (reminder: "
                                                    "function must be declared in the correct contract)" % method_name)
    sig = context.sigs[contract_name][method_name]
    contract_address = parse_expr(stmt.func.value.args[0], context)
    inargs, inargsize = pack_arguments(sig, [parse_expr(arg, context) for arg in stmt.args], context)
    o = LLLnode.from_list(['seq',
                            ['assert', ['extcodesize', ['mload', contract_address]]],
                            ['assert', ['ne', 'address', ['mload', contract_address]]],
                            ['assert', ['call', ['gas'], ['mload', contract_address], 0, inargs, inargsize, 0, 0]]],
                                    typ=None, location='memory', pos=getpos(stmt))
    return o


def external_contract_call_expr(expr, context):
    contract_name = expr.func.value.func.id
    if contract_name not in context.sigs:
        raise VariableDeclarationException("Contract not declared yet: %s" % contract_name)
    method_name = expr.func.attr
    if method_name not in context.sigs[contract_name]:
        raise VariableDeclarationException("Function not declared yet: %s (reminder: "
                                                    "function must be declared in the correct contract)" % method_name)
    sig = context.sigs[contract_name][method_name]
    contract_address = parse_expr(expr.func.value.args[0], context)
    inargs, inargsize = pack_arguments(sig, [parse_expr(arg, context) for arg in expr.args], context)
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    if isinstance(sig.output_type, BaseType):
        returner = output_placeholder
    elif isinstance(sig.output_type, ByteArrayType):
        returner = output_placeholder + 32
    else:
        raise TypeMismatchException("Invalid output type: %r" % sig.output_type, expr)
    o = LLLnode.from_list(['seq',
                            ['assert', ['extcodesize', ['mload', contract_address]]],
                            ['assert', ['ne', 'address', ['mload', contract_address]]],
                            ['assert', ['call', ['gas'], ['mload', contract_address], 0,
                            inargs, inargsize,
                            output_placeholder, get_size_of_type(sig.output_type) * 32]],
                            returner], typ=sig.output_type, location='memory', pos=getpos(expr))
    return o


# Parse an expression
def parse_expr(expr, context):
    if isinstance(expr, LLLnode):
        return expr
    # Numbers (integers or decimals)
    elif isinstance(expr, ast.Num):
        orignum = get_original_if_0x_prefixed(expr, context)
        if orignum is None and isinstance(expr.n, int):
            if not (-2**127 + 1 <= expr.n <= 2**127 - 1):
                raise InvalidLiteralException("Number out of range: " + str(expr.n), expr)
            return LLLnode.from_list(expr.n, typ=BaseType('num', None), pos=getpos(expr))
        elif isinstance(expr.n, float):
            numstring, num, den = get_number_as_fraction(expr, context)
            if not (-2**127 * den < num < 2**127 * den):
                raise InvalidLiteralException("Number out of range: " + numstring, expr)
            if DECIMAL_DIVISOR % den:
                raise InvalidLiteralException("Too many decimal places: " + numstring, expr)
            return LLLnode.from_list(num * DECIMAL_DIVISOR // den, typ=BaseType('decimal', None), pos=getpos(expr))
        elif len(orignum) == 42:
            if checksum_encode(orignum) != orignum:
                raise InvalidLiteralException("Address checksum mismatch. If you are sure this is the "
                                              "right address, the correct checksummed form is: " +
                                              checksum_encode(orignum), expr)
            return LLLnode.from_list(expr.n, typ=BaseType('address'), pos=getpos(expr))
        elif len(orignum) == 66:
            return LLLnode.from_list(expr.n, typ=BaseType('bytes32'), pos=getpos(expr))
        else:
            raise InvalidLiteralException("Cannot read 0x value with length %d. Expecting 42 (address incl 0x) or 66 (bytes32 incl 0x)"
                                          % len(orignum), expr)
    # Byte array literals
    elif isinstance(expr, ast.Str):
        bytez = b''
        for c in expr.s:
            if ord(c) >= 256:
                raise InvalidLiteralException("Cannot insert special character %r into byte array" % c, expr)
            bytez += bytes([ord(c)])
        placeholder = context.new_placeholder(ByteArrayType(len(bytez)))
        seq = []
        seq.append(['mstore', placeholder, len(bytez)])
        for i in range(0, len(bytez), 32):
            seq.append(['mstore', ['add', placeholder, i + 32], bytes_to_int((bytez + b'\x00' * 31)[i: i + 32])])
        return LLLnode.from_list(['seq'] + seq + [placeholder], typ=ByteArrayType(len(bytez)), location='memory', pos=getpos(expr))
    # True, False, None constants
    elif isinstance(expr, ast.NameConstant):
        if expr.value is True:
            return LLLnode.from_list(1, typ='bool', pos=getpos(expr))
        elif expr.value is False:
            return LLLnode.from_list(0, typ='bool', pos=getpos(expr))
        elif expr.value is None:
            return LLLnode.from_list(None, typ=NullType(), pos=getpos(expr))
        else:
            raise Exception("Unknown name constant: %r" % expr.value.value)
    # Variable names
    elif isinstance(expr, ast.Name):
        if expr.id == 'self':
            return LLLnode.from_list(['address'], typ='address', pos=getpos(expr))
        if expr.id == 'true':
            return LLLnode.from_list(1, typ='bool', pos=getpos(expr))
        if expr.id == 'false':
            return LLLnode.from_list(0, typ='bool', pos=getpos(expr))
        if expr.id == 'null':
            return LLLnode.from_list(None, typ=NullType(), pos=getpos(expr))
        if expr.id in context.vars:
            var = context.vars[expr.id]
            return LLLnode.from_list(var.pos, typ=var.typ, location='memory', pos=getpos(expr), annotation=expr.id, mutable=var.mutable)
        else:
            raise VariableDeclarationException("Undeclared variable: " + expr.id, expr)
    # x.y or x[5]
    elif isinstance(expr, ast.Attribute):
        # x.balance: balance of address x
        if expr.attr == 'balance':
            addr = parse_value_expr(expr.value, context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException("Type mismatch: balance keyword expects an address as input", expr)
            return LLLnode.from_list(['balance', addr], typ=BaseType('num', {'wei': 1}), location=None, pos=getpos(expr))
        # x.codesize: codesize of address x
        elif expr.attr == 'codesize' or expr.attr == 'is_contract':
            addr = parse_value_expr(expr.value, context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException(f"Type mismatch: {expr.attr} keyword expects an address as input", expr)
            if expr.attr == 'codesize':
                output_type = 'num'
            else:
                output_type = 'bool'
            return LLLnode.from_list(['extcodesize', addr], typ=BaseType(output_type), location=None, pos=getpos(expr))
        # self.x: global attribute
        elif isinstance(expr.value, ast.Name) and expr.value.id == "self":
            if expr.attr not in context.globals:
                raise VariableDeclarationException("Persistent variable undeclared: " + expr.attr, expr)
            var = context.globals[expr.attr]
            return LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(expr), annotation='self.' + expr.attr)
        # Reserved keywords
        elif isinstance(expr.value, ast.Name) and expr.value.id in ("msg", "block", "tx"):
            key = expr.value.id + "." + expr.attr
            if key == "msg.sender":
                return LLLnode.from_list(['caller'], typ='address', pos=getpos(expr))
            elif key == "msg.value":
                if not context.is_payable:
                    raise NonPayableViolationException("Cannot use msg.value in a non-payable function", expr)
                return LLLnode.from_list(['callvalue'], typ=BaseType('num', {'wei': 1}), pos=getpos(expr))
            elif key == "block.difficulty":
                return LLLnode.from_list(['difficulty'], typ='num', pos=getpos(expr))
            elif key == "block.timestamp":
                return LLLnode.from_list(['timestamp'], typ=BaseType('num', {'sec': 1}, True), pos=getpos(expr))
            elif key == "block.coinbase":
                return LLLnode.from_list(['coinbase'], typ='address', pos=getpos(expr))
            elif key == "block.number":
                return LLLnode.from_list(['number'], typ='num', pos=getpos(expr))
            elif key == "block.prevhash":
                return LLLnode.from_list(['blockhash', ['sub', 'number', 1]], typ='bytes32', pos=getpos(expr))
            elif key == "tx.origin":
                return LLLnode.from_list(['origin'], typ='address', pos=getpos(expr))
            else:
                raise Exception("Unsupported keyword: " + key)
        # Other variables
        else:
            sub = parse_variable_location(expr.value, context)
            if not isinstance(sub.typ, StructType):
                raise TypeMismatchException("Type mismatch: member variable access not expected", expr.value)
            attrs = sorted(sub.typ.members.keys())
            if expr.attr not in attrs:
                raise TypeMismatchException("Member %s not found. Only the following available: %s" % (expr.attr, " ".join(attrs)), expr)
            return add_variable_offset(sub, expr.attr)
    elif isinstance(expr, ast.Subscript):
        sub = parse_variable_location(expr.value, context)
        if isinstance(sub.typ, (MappingType, ListType)):
            if 'value' not in vars(expr.slice):
                raise StructureException("Array access must access a single element, not a slice", expr)
            index = parse_value_expr(expr.slice.value, context)
        elif isinstance(sub.typ, TupleType):
            if not isinstance(expr.slice.value, ast.Num) or expr.slice.value.n < 0 or expr.slice.value.n >= len(sub.typ.members):
                raise TypeMismatchException("Tuple index invalid", expr.slice.value)
            index = expr.slice.value.n
        else:
            raise TypeMismatchException("Bad subscript attempt", expr.value)
        o = add_variable_offset(sub, index)
        o.mutable = sub.mutable
        return o
    # Arithmetic operations
    elif isinstance(expr, ast.BinOp):
        left = parse_value_expr(expr.left, context)
        right = parse_value_expr(expr.right, context)
        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            raise TypeMismatchException("Unsupported types for arithmetic op: %r %r" % (left.typ, right.typ), expr)
        ltyp, rtyp = left.typ.typ, right.typ.typ
        if isinstance(expr.op, (ast.Add, ast.Sub)):
            if left.typ.unit != right.typ.unit and left.typ.unit is not None and right.typ.unit is not None:
                raise TypeMismatchException("Unit mismatch: %r %r" % (left.typ.unit, right.typ.unit), expr)
            if left.typ.positional and right.typ.positional and isinstance(expr.op, ast.Add):
                raise TypeMismatchException("Cannot add two positional units!", expr)
            new_unit = left.typ.unit or right.typ.unit
            new_positional = left.typ.positional ^ right.typ.positional  # xor, as subtracting two positionals gives a delta
            op = 'add' if isinstance(expr.op, ast.Add) else 'sub'
            if ltyp == rtyp:
                o = LLLnode.from_list([op, left, right], typ=BaseType(ltyp, new_unit, new_positional), pos=getpos(expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right],
                                      typ=BaseType('decimal', new_unit, new_positional), pos=getpos(expr))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit, new_positional), pos=getpos(expr))
            else:
                raise Exception("How did I get here? %r %r" % (ltyp, rtyp))
        elif isinstance(expr.op, ast.Mult):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot multiply positional values!", expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit)
            if ltyp == rtyp == 'num':
                o = LLLnode.from_list(['mul', left, right], typ=BaseType('num', new_unit), pos=getpos(expr))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                ['sdiv', 'ans', DECIMAL_DIVISOR]]]]], typ=BaseType('decimal', new_unit), pos=getpos(expr))
            elif (ltyp == 'num' and rtyp == 'decimal') or (ltyp == 'decimal' and rtyp == 'num'):
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                'ans']]]], typ=BaseType('decimal', new_unit), pos=getpos(expr))
        elif isinstance(expr.op, ast.Div):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot divide positional values!", expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit, div=True)
            if rtyp == 'num':
                o = LLLnode.from_list(['sdiv', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit), pos=getpos(expr))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'l', left, ['with', 'r', ['clamp_nonzero', right],
                                            ['sdiv', ['mul', 'l', DECIMAL_DIVISOR], 'r']]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['sdiv', ['mul', left, DECIMAL_DIVISOR ** 2], ['clamp_nonzero', right]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(expr))
        elif isinstance(expr.op, ast.Mod):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot use positional values as modulus arguments!", expr)
            if left.typ.unit != right.typ.unit and left.typ.unit is not None and right.typ.unit is not None:
                raise TypeMismatchException("Modulus arguments must have same unit", expr)
            new_unit = left.typ.unit or right.typ.unit
            if ltyp == rtyp:
                o = LLLnode.from_list(['smod', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit), pos=getpos(expr))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list(['smod', left, ['mul', ['clamp_nonzero', right], DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['smod', ['mul', left, DECIMAL_DIVISOR], right],
                                      typ=BaseType('decimal', new_unit), pos=getpos(expr))
        elif isinstance(expr.op, ast.Pow):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot use positional values as exponential arguments!", expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit)
            if ltyp == rtyp == 'num':
                o = LLLnode.from_list(['exp', left, right], typ=BaseType('num', new_unit), pos=getpos(expr))
            else:
                raise TypeMismatchException('Only whole number exponents are supported', expr)
        else:
            raise Exception("Unsupported binop: %r" % expr.op)
        if o.typ.typ == 'num':
            return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINNUM], o, ['mload', MemoryPositions.MAXNUM]], typ=o.typ, pos=getpos(expr))
        elif o.typ.typ == 'decimal':
            return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINDECIMAL], o, ['mload', MemoryPositions.MAXDECIMAL]], typ=o.typ, pos=getpos(expr))
        else:
            raise Exception("%r %r" % (o, o.typ))
    # Comparison operations
    elif isinstance(expr, ast.Compare):
        left = parse_value_expr(expr.left, context)
        right = parse_value_expr(expr.comparators[0], context)
        if not are_units_compatible(left.typ, right.typ) and not are_units_compatible(right.typ, left.typ):
            raise TypeMismatchException("Can't compare values with different units!", expr)
        if len(expr.ops) != 1:
            raise StructureException("Cannot have a comparison with more than two elements", expr)
        if isinstance(expr.ops[0], ast.Gt):
            op = 'sgt'
        elif isinstance(expr.ops[0], ast.GtE):
            op = 'sge'
        elif isinstance(expr.ops[0], ast.LtE):
            op = 'sle'
        elif isinstance(expr.ops[0], ast.Lt):
            op = 'slt'
        elif isinstance(expr.ops[0], ast.Eq):
            op = 'eq'
        elif isinstance(expr.ops[0], ast.NotEq):
            op = 'ne'
        else:
            raise Exception("Unsupported comparison operator")
        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            if op not in ('eq', 'ne'):
                raise TypeMismatchException("Invalid type for comparison op", expr)
        ltyp, rtyp = left.typ.typ, right.typ.typ
        if ltyp == rtyp:
            return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(expr))
        elif ltyp == 'decimal' and rtyp == 'num':
            return LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]], typ='bool', pos=getpos(expr))
        elif ltyp == 'num' and rtyp == 'decimal':
            return LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right], typ='bool', pos=getpos(expr))
        else:
            raise TypeMismatchException("Unsupported types for comparison: %r %r" % (ltyp, rtyp), expr)
    # Boolean logical operations
    elif isinstance(expr, ast.BoolOp):
        if len(expr.values) != 2:
            raise StructureException("Expected two arguments for a bool op", expr)
        left = parse_value_expr(expr.values[0], context)
        right = parse_value_expr(expr.values[1], context)
        if not is_base_type(left.typ, 'bool') or not is_base_type(right.typ, 'bool'):
            raise TypeMismatchException("Boolean operations can only be between booleans!", expr)
        if isinstance(expr.op, ast.And):
            op = 'and'
        elif isinstance(expr.op, ast.Or):
            op = 'or'
        else:
            raise Exception("Unsupported bool op: " + expr.op)
        return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(expr))
    # Unary operations (only "not" supported)
    elif isinstance(expr, ast.UnaryOp):
        operand = parse_value_expr(expr.operand, context)
        if isinstance(expr.op, ast.Not):
            # Note that in the case of bool, num, address, decimal, num256 AND bytes32,
            # a zero entry represents false, all others represent true
            return LLLnode.from_list(["iszero", operand], typ='bool', pos=getpos(expr))
        elif isinstance(expr.op, ast.USub):
            if not is_numeric_type(operand.typ):
                raise TypeMismatchException("Unsupported type for negation: %r" % operand.typ, operand)
            return LLLnode.from_list(["sub", 0, operand], typ=operand.typ, pos=getpos(expr))
        else:
            raise StructureException("Only the 'not' unary operator is supported")
    # Function calls
    elif isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id in dispatch_table:
            return dispatch_table[expr.func.id](expr, context)
        elif isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Name) and expr.func.value.id == "self":
            method_name = expr.func.attr
            if method_name not in context.sigs['self']:
                raise VariableDeclarationException("Function not declared yet (reminder: functions cannot "
                                                   "call functions later in code than themselves): %s" % expr.func.attr)
            sig = context.sigs['self'][expr.func.attr]
            inargs, inargsize = pack_arguments(sig, [parse_expr(arg, context) for arg in expr.args], context)
            output_placeholder = context.new_placeholder(typ=sig.output_type)
            if isinstance(sig.output_type, BaseType):
                returner = output_placeholder
            elif isinstance(sig.output_type, ByteArrayType):
                returner = output_placeholder + 32
            else:
                raise TypeMismatchException("Invalid output type: %r" % sig.output_type, expr)
            o = LLLnode.from_list(['seq',
                                        ['assert', ['call', ['gas'], ['address'], 0,
                                                        inargs, inargsize,
                                                        output_placeholder, get_size_of_type(sig.output_type) * 32]],
                                        returner], typ=sig.output_type, location='memory', pos=getpos(expr))
            o.gas += sig.gas
            return o
        elif isinstance(expr.func, ast.Attribute) and isinstance(expr.func.value, ast.Call):
            return external_contract_call_expr(expr, context)
        else:
            raise StructureException("Unsupported operator: %r" % ast.dump(expr), expr)
    # List literals
    elif isinstance(expr, ast.List):
        if not len(expr.elts):
            raise StructureException("List must have elements", expr)
        o = []
        out_type = None
        for elt in expr.elts:
            o.append(parse_expr(elt, context))
            if not out_type:
                out_type = o[-1].typ
            elif len(o) > 1 and o[-1].typ != out_type:
                out_type = MixedType()
        return LLLnode.from_list(["multi"] + o, typ=ListType(out_type, len(o)), pos=getpos(expr))
    # Struct literals
    elif isinstance(expr, ast.Dict):
        o = {}
        members = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, ast.Name) or not is_varname_valid(key.id):
                raise TypeMismatchException("Invalid member variable for struct: %r" % vars(key).get('id', key), key)
            if key.id in o:
                raise TypeMismatchException("Member variable duplicated: " + key.id, key)
            o[key.id] = parse_expr(value, context)
            members[key.id] = o[key.id].typ
        return LLLnode.from_list(["multi"] + [o[key] for key in sorted(list(o.keys()))], typ=StructType(members), pos=getpos(expr))

    # Tuple literals
    elif isinstance(expr, ast.Tuple):
        if not len(expr.elts):
            raise StructureException("Tuple must have elements", expr)
        o = []
        out_type = None
        for elt in expr.elts:
            o.append(parse_expr(elt, context))
        return LLLnode.from_list(["multi"] + o, typ=TupleType(o), pos=getpos(expr))

    raise Exception("Unsupported operator: %r" % ast.dump(expr))


# Parse an expression that represents an address in memory or storage
def parse_variable_location(expr, context):
    o = parse_expr(expr, context)
    if not o.location:
        raise Exception("Looking for a variable location, instead got a value")
    return o


# Parse an expression that results in a value
def parse_value_expr(expr, context):
    return unwrap_location(parse_expr(expr, context))


# Create an x=y statement, where the types may be compound
def make_setter(left, right, location):
    # Basic types
    if isinstance(left.typ, BaseType):
        right = base_type_conversion(right, right.typ, left.typ)
        if location == 'storage':
            return LLLnode.from_list(['sstore', left, right], typ=None)
        elif location == 'memory':
            return LLLnode.from_list(['mstore', left, right], typ=None)
    # Byte arrays
    elif isinstance(left.typ, ByteArrayType):
        return make_byte_array_copier(left, right)
    # Can't copy mappings
    elif isinstance(left.typ, MappingType):
        raise TypeMismatchException("Cannot copy mappings; can only copy individual elements")
    # Arrays
    elif isinstance(left.typ, ListType):
        # Cannot do something like [a, b, c] = [1, 2, 3]
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, (ListType, NullType)):
            raise TypeMismatchException("Setter type mismatch: left side is array, right side is %r" % right.typ)
        left_token = LLLnode.from_list('_L', typ=left.typ, location=left.location)
        if left.location == "storage":
            left = LLLnode.from_list(['sha3_32', left], typ=left.typ, location="storage_prehashed")
            left_token.location = "storage_prehashed"
        # Type checks
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, ListType):
                raise TypeMismatchException("Left side is array, right side is not")
            if left.typ.count != right.typ.count:
                raise TypeMismatchException("Mismatched number of elements")
        # If the right side is a literal
        if right.value == "multi":
            if len(right.args) != left.typ.count:
                raise TypeMismatchException("Mismatched number of elements")
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        right.args[i], location))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        LLLnode.from_list(None, typ=NullType()), location))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            subs = []
            for i in range(left.typ.count):
                subs.append(make_setter(add_variable_offset(left_token, LLLnode.from_list(i, typ='num')),
                                        add_variable_offset(right_token, LLLnode.from_list(i, typ='num')), location))
            return LLLnode.from_list(['with', '_L', left, ['with', '_R', right, ['seq'] + subs]], typ=None)
    # Structs
    elif isinstance(left.typ, (StructType, TupleType)):
        if left.value == "multi":
            raise Exception("Target of set statement must be a single item")
        if not isinstance(right.typ, NullType):
            if not isinstance(right.typ, left.typ.__class__):
                raise TypeMismatchException("Setter type mismatch: left side is %r, right side is %r" % (left.typ, right.typ))
            if isinstance(left.typ, StructType):
                for k in left.typ.members:
                    if k not in right.typ.members:
                        raise TypeMismatchException("Keys don't match for structs, missing %s" % k)
                for k in right.typ.members:
                    if k not in left.typ.members:
                        raise TypeMismatchException("Keys don't match for structs, extra %s" % k)
            else:
                if len(left.typ.members) != len(right.typ.members):
                    raise TypeMismatchException("Tuple lengths don't match, %d vs %d" % (len(left.typ.members), len(right.typ.members)))
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
                raise TypeMismatchException("Mismatched number of elements")
            subs = []
            for i, typ in enumerate(keyz):
                subs.append(make_setter(add_variable_offset(left_token, typ), right.args[i], location))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a null
        elif isinstance(right.typ, NullType):
            subs = []
            for typ in keyz:
                subs.append(make_setter(add_variable_offset(left_token, typ), LLLnode.from_list(None, typ=NullType()), location))
            return LLLnode.from_list(['with', '_L', left, ['seq'] + subs], typ=None)
        # If the right side is a variable
        else:
            right_token = LLLnode.from_list('_R', typ=right.typ, location=right.location)
            subs = []
            for typ in keyz:
                subs.append(make_setter(add_variable_offset(left_token, typ), add_variable_offset(right_token, typ), location))
            return LLLnode.from_list(['with', '_L', left, ['with', '_R', right, ['seq'] + subs]], typ=None)
    else:
        raise Exception("Invalid type for setters")


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


def pack_logging_topics(event_id, args, topics_types, context):
    topics = [event_id]
    topics_count = 1
    stored_topics = ['seq']
    for pos, typ in enumerate(topics_types):
        arg = args[pos]
        topics_count += 1
        if isinstance(arg, ast.Str):
            stored_topics.append(parse_value_expr(arg, context))
            topics.append(['mload', stored_topics[-1].to_list()[-1][-1][-1] + 32])
        else:
            input = parse_value_expr(arg, context)
            input = base_type_conversion(input, input.typ, typ)
            topics.append(input)
    return topics, stored_topics


def pack_args_by_32(holder, maxlen, arg, typ, context, placeholder):
    if isinstance(typ, BaseType):
            input = parse_expr(arg, context)
            input = base_type_conversion(input, input.typ, typ)
            holder.append(LLLnode.from_list(['mstore', placeholder, input], typ=typ, location='memory'))
    elif isinstance(typ, ByteArrayType):
        bytez = b''
        for c in arg.s:
            if ord(c) >= 256:
                raise InvalidLiteralException("Cannot insert special character %r into byte array" % c)
            bytez += bytes([ord(c)])
        bytez_length = len(bytez)
        if len(bytez) > 32:
            raise InvalidLiteralException("Can only log a maximum of 32 bytes at a time.")
        holder.append(LLLnode.from_list(['mstore', placeholder, bytes_to_int(bytez + b'\x00' * (32 - bytez_length))], typ=typ, location='memory'))
    elif isinstance(typ, ListType):
            maxlen += (typ.count - 1) * 32
            typ = typ.subtype
            holder, maxlen = pack_args_by_32(holder, maxlen, arg.elts[0], typ, context, placeholder)
            for j, arg2 in enumerate(arg.elts[1:]):
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, context.new_placeholder(BaseType(32)))
    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(types, args, context):
    # Checks to see if there's any data
    if not args:
        return ['seq'], 0, 0
    holder = ['seq']
    maxlen = len(args) * 32
    for i, (arg, typ) in enumerate(zip(args, types)):
        holder, maxlen = pack_args_by_32(holder, maxlen, arg, typ, context, context.new_placeholder(BaseType(32)))
    return holder, maxlen, holder[1].to_list()[1][0]


# Pack function arguments for a call
def pack_arguments(signature, args, context):
    placeholder_typ = ByteArrayType(maxlen=sum([get_size_of_type(arg.typ) for arg in signature.args]) * 32 + 32)
    placeholder = context.new_placeholder(placeholder_typ)
    setters = [['mstore', placeholder, signature.method_id]]
    needpos = False
    for i, (arg, typ) in enumerate(zip(args, [arg.typ for arg in signature.args])):
        if isinstance(typ, BaseType):
            setters.append(make_setter(LLLnode.from_list(placeholder + 32 + i * 32, typ=typ), arg, 'memory'))
        elif isinstance(typ, ByteArrayType):
            setters.append(['mstore', placeholder + 32 + i * 32, '_poz'])
            arg_copy = LLLnode.from_list('_s', typ=arg.typ, location=arg.location)
            target = LLLnode.from_list(['add', placeholder + 32, '_poz'], typ=typ, location='memory')
            setters.append(['with', '_s', arg, ['seq',
                                                    make_byte_array_copier(target, arg_copy),
                                                    ['set', '_poz', ['add', 32, ['add', '_poz', get_length(arg_copy)]]]]])
            needpos = True
        else:
            raise TypeMismatchException("Cannot pack argument of type %r" % typ)
    if needpos:
        return LLLnode.from_list(['with', '_poz', len(args) * 32, ['seq'] + setters + [placeholder + 28]],
                                 typ=placeholder_typ, location='memory'), \
            placeholder_typ.maxlen - 28
    else:
        return LLLnode.from_list(['seq'] + setters + [placeholder + 28], typ=placeholder_typ, location='memory'), \
            placeholder_typ.maxlen - 28


def parse_to_lll(kode):
    code = parse(kode)
    return parse_tree_to_lll(code, kode)
