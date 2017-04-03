try:
    from Crypto.Hash import keccak
    sha3_256 = lambda x: keccak.new(digest_bits=256, data=x).digest()
except ImportError:
    import sha3
    sha3_256 = lambda x: sha3._sha3.sha3_256(x).digest()

import ast, tokenize, binascii
from io import BytesIO
from .opcodes import opcodes, pseudo_opcodes
import copy
from .types import NodeType, BaseType, ListType, MappingType, StructType, \
    MixedType, NullType, ByteArrayType, TupleType
from .types import base_types, parse_type, canonicalize_type, is_base_type, \
    is_numeric_type, get_size_of_type, is_varname_valid
from .types import combine_units, are_units_compatible, set_default_units
from .exceptions import InvalidTypeException, TypeMismatchException, \
    VariableDeclarationException, StructureException, ConstancyViolationException, \
    InvalidTypeException, InvalidLiteralException
from .functions import dispatch_table, stmt_dispatch_table
from .parser_utils import LLLnode, make_byte_array_copier, get_number_as_fraction, \
    get_original_if_0x_prefixed
from .utils import fourbytes_to_int, hex_to_int, bytes_to_int, checksum_encode, \
    DECIMAL_DIVISOR, RESERVED_MEMORY, ADDRSIZE_POS, MAXNUM_POS, MINNUM_POS, \
    MAXDECIMAL_POS, MINDECIMAL_POS, FREE_VAR_SPACE, BLANK_SPACE, FREE_LOOP_INDEX

try:
    x = ast.AnnAssign
except:
    raise Exception("Requires python 3.6 or higher for annotation support")

# Converts code to parse tree
def parse(code):
    o = ast.parse(code)
    decorate_ast_with_source(o, code)
    return o.body

def parse_line(code):
    o = ast.parse(code).body[0]
    decorate_ast_with_source(o, code)
    return o

def decorate_ast_with_source(_ast, code):

    class MyVisitor(ast.NodeVisitor):
        def visit(self, node):
            self.generic_visit(node)
            node.source_code = code

    MyVisitor().visit(_ast)

# Make a getter for a variable
def _mk_getter_helper(typ, depth=0):
    if isinstance(typ, BaseType):
        return [("", "", "", repr(typ))]
    elif isinstance(typ, ByteArrayType):
        return [("", "", "", repr(typ))]
    elif isinstance(typ, ListType):
        o = []
        for funname, head, tail, base in _mk_getter_helper(typ.subtype, depth+1):
            o.append((funname, ("arg%d: num, " % depth) + head, ("[arg%d]" % depth) + tail, base))
        return o
    elif isinstance(typ, MappingType):
        o = []
        for funname, head, tail, base in _mk_getter_helper(typ.valuetype, depth+1):
            o.append((funname, ("arg%d: %r, " % (depth, typ.keytype)) + head, ("[arg%d]" % depth) + tail, base))
        return o
    elif isinstance(typ, StructType):
        o = []
        for k, v in typ.members.items():
            for funname, head, tail, base in _mk_getter_helper(v, depth):
                o.append(("__"+k+funname, head, "."+k+tail, base))
        return o
    else:
        raise Exception("Unexpected type")

def update_base(base):
    return '('+base+')(const)' if '(' not in base else base.rstrip(')') + ', const)'

def mk_getter(varname, typ):
    funs = _mk_getter_helper(typ)
    return ['def get_%s%s(%s) -> %s: return self.%s%s' % (varname, funname, head.rstrip(', '), update_base(base), varname, tail)
            for (funname, head, tail, base) in funs]

# Parse top-level functions and variables
def get_defs_and_globals(code):
    _globals = {}
    _defs = []
    _getters = []
    for item in code:
        if isinstance(item, ast.AnnAssign):
            if not isinstance(item.target, ast.Name):
                raise StructureException("Can only assign type to variable in top-level statement", item)
            if item.target.id in _globals:
                raise VariableDeclarationException("Cannot declare a persistent variable twice!", item.target)
            if len(_defs):
                raise StructureException("Global variables must all come before function definitions", item)
            if isinstance(item.annotation, ast.Call) and item.annotation.func.id == "public":
                if len(item.annotation.args) != 1:
                    raise StructureException("Public expects one arg (the type)")
                typ = parse_type(item.annotation.args[0], 'storage')
                _globals[item.target.id] = (len(_globals), typ)
                for getter in mk_getter(item.target.id, typ):
                    _getters.append(parse_line(getter))
            else:
                _globals[item.target.id] = (len(_globals), parse_type(item.annotation, 'storage'))
        elif isinstance(item, ast.FunctionDef):
            _defs.append(item)
        else:
            raise StructureException("Invalid top-level statement", item)
    return _defs + _getters, _globals

# Header code
def mk_initial():
    return LLLnode.from_list(['seq',
                                ['mstore', 28, ['calldataload', 0]],
                                ['mstore', ADDRSIZE_POS, 2**160],
                                ['mstore', MAXNUM_POS, 2**128 - 1],
                                ['mstore', MINNUM_POS, -2**128 + 1],
                                ['mstore', MAXDECIMAL_POS, (2**128 - 1) * DECIMAL_DIVISOR],
                                ['mstore', MINDECIMAL_POS, (-2**128 + 1) * DECIMAL_DIVISOR],
                             ], typ=None)

# Get function details
def get_func_details(code):
    name = code.name
    # Determine the arguments, expects something of the form def foo(arg1: num, arg2: num ...
    args = []
    for arg in code.args.args:
        typ = arg.annotation
        if not isinstance(arg.arg, str):
            raise VariableDeclarationException("Argument name invalid", arg)
        if not typ:
            raise InvalidTypeException("Argument must have type", arg)
        if not is_varname_valid(arg.arg):
            raise VariableDeclarationException("Argument name invalid or reserved: "+arg.arg, arg)
        if arg.arg in (x[0] for x in args):
            raise VariableDeclarationException("Duplicate function argument name: "+arg.arg, arg)
        if name == '__init__':
            args.append((arg.arg, -32 * len(code.args.args) + 32 * len(args), parse_type(typ, None)))
        else:
            args.append((arg.arg, 4 + 32 * len(args), parse_type(typ, None)))
    # Determine the return type and whether or not it's constant. Expects something
    # of the form:
    # def foo(): ...
    # def foo() -> num: ... 
    # def foo() -> num(const): ...
    const = False
    if not code.returns:
        output_type = None
    elif isinstance(code.returns, ast.Call):
        consts = [arg for arg in code.returns.args if isinstance(arg, ast.Name) and arg.id == 'const']
        units = [arg for arg in code.returns.args if arg not in consts]
        if len(consts) > 1:
            raise InvalidTypeException("Expecting at most one const keyword", code.returns)
        const = len(consts) == 1
        if units:
            typ = ast.Call(func=code.returns.func, args=units)
        else:
            typ = code.returns.func
        output_type = parse_type(typ, None)
    elif isinstance(code.returns, (ast.Name, ast.Compare)):
        output_type = parse_type(code.returns, None)
    else:
        raise InvalidTypeException("Output type invalid or unsupported: %r" % parse_type(code.returns, None), code.returns)
    # Output type can only be base type or none
    assert isinstance(output_type, (BaseType, ByteArrayType, (None).__class__))
    # Get the four-byte method id
    sig = name + '(' + ','.join([canonicalize_type(parse_type(arg.annotation, None)) for arg in code.args.args]) + ')'
    method_id = fourbytes_to_int(sha3_256(bytes(sig, 'utf-8'))[:4])
    return name, args, output_type, const, sig, method_id

# Contains arguments, variables, etc
class Context():
    def __init__(self, args=None, vars=None, globals=None, forvars=None, return_type=None, is_constant=False, origcode=''):
        self.args = args or {}
        self.vars = vars or {}
        self.globals = globals or {}
        self.forvars = forvars or {}
        self.return_type = return_type
        self.is_constant = is_constant
        self.placeholder_count = 1
        self.origcode = origcode

    def new_variable(self, name, typ):
        if not is_varname_valid(name):
            raise VariableDeclarationException("Variable name invalid or reserved: "+name)
        if name in self.vars or name in self.args or name in self.globals:
            raise VariableDeclarationException("Duplicate variable name: %s" % name)
        pos = self.get_next_mem()
        self.vars[name] = pos, typ
        self.vars['_next_mem'] = pos + 32 * get_size_of_type(typ)
        return pos

    def new_placeholder(self, typ):
        name = '_placeholder_'+str(self.placeholder_count)
        self.placeholder_count += 1
        return self.new_variable(name, typ)

    def get_next_mem(self):
        return self.vars.get('_next_mem', RESERVED_MEMORY)

# Is a function the initializer?
def is_initializer(code):
    return code.name == '__init__'

# Get ABI signature
def mk_full_signature(code):
    o = []
    _defs, _globals = get_defs_and_globals(code)
    for code in _defs:
        name, args, output_type, const, sig, method_id = get_func_details(code)
        o.append({
            "name": sig,
            "outputs": [{"type": canonicalize_type(output_type), "name": "out"}] if output_type else [],
            "inputs": [{"type": canonicalize_type(typ), "name": nam} for nam, loc, typ in args],
            "constant": const,
            "type": "constructor" if name == "__init__" else "function"
        })
    return o
        
# Main python parse tree => LLL method
def parse_tree_to_lll(code, origcode):
    _defs, _globals = get_defs_and_globals(code)
    _defnames = [_def.name for _def in _defs]
    if len(set(_defnames)) < len(_defs):
        raise VariableDeclarationException("Duplicate function name: %s" % [name for name in _defnames if _defnames.count(name) > 1][0])
    # Initialization function
    initfunc = [_def for _def in _defs if is_initializer(_def)]
    # Regular functions
    otherfuncs = [_def for _def in _defs if not is_initializer(_def)]
    if not initfunc and not otherfuncs:
        return LLLnode.from_list('pass')
    if not initfunc and otherfuncs:
        return LLLnode.from_list(['return', 0, ['lll', ['seq', mk_initial()] + [parse_func(_def, _globals, origcode) for _def in otherfuncs], 0]], typ=None)
    elif initfunc and not otherfuncs:
        return LLLnode.from_list(['seq', mk_initial(), parse_func(initfunc[0], _globals, origcode), ['selfdestruct']], typ=None)
    elif initfunc and otherfuncs:
        return LLLnode.from_list(['seq', mk_initial(), parse_func(initfunc[0], _globals, origcode),
                                    ['return', 0, ['lll', ['seq', mk_initial()] + [parse_func(_def, _globals, origcode) for _def in otherfuncs], 0]]],
                                 typ=None)

# Checks that an input matches its type
def make_clamper(dataloc, typ):
    if dataloc >= 0:
        data_decl = ['calldataload', dataloc]
    else:
        data_decl = ['seq', ['codecopy', FREE_VAR_SPACE, ['sub', ['codesize'], -dataloc], 32], ['mload', FREE_VAR_SPACE]]
    if is_base_type(typ, 'num'):
        return LLLnode.from_list(['clamp', ['mload', MINNUM_POS], data_decl, ['mload', MAXNUM_POS]], typ=typ)
    elif is_base_type(typ, 'bool'):
        return LLLnode.from_list(['uclamplt', data_decl, 2], typ=typ)
    elif is_base_type(typ, 'address'):
        return LLLnode.from_list(['uclamplt', data_decl, ['mload', ADDRSIZE_POS]], typ=typ)
    else:
        return LLLnode.from_list('pass')

# Parses a function declaration
def parse_func(code, _globals, origcode, _vars=None):
    name, args, output_type, const, sig, method_id = get_func_details(code)
    # Check for duplicate variables with globals
    for arg in args:
        if arg[0] in _globals:
            raise VariableDeclarationException("Variable name duplicated between function arguments and globals: "+arg[0])
    # Create a context
    context = Context(args={a[0]: (a[1], a[2]) for a in args}, globals=_globals, vars=_vars or {},
                      return_type=output_type, is_constant=const, origcode=origcode)
    # Create "clampers" (input well-formedness checkers)
    clampers = [make_clamper(loc, typ) for _, loc, typ in args]
    # Return function body
    if name == '__init__':
        return LLLnode.from_list(['seq'] + clampers + [parse_body(code.body, context)])
    else:
        return LLLnode.from_list(['if',
                                    ['eq', ['mload', 0], method_id],
                                    ['seq'] + clampers + [parse_body(c, context) for c in code.body]
                                 ], typ=None)
    
# Parse a piece of code
def parse_body(code, context):
    if not isinstance(code, list):
        return parse_stmt(code, context)
    o = []
    for stmt in code:
        o.append(parse_stmt(stmt, context))
    return LLLnode.from_list(['seq'] + o)

# Take a value representing a storage location, and descend down to an element or member variable
def add_variable_offset(parent, key):
    typ, location = parent.typ, parent.location
    if isinstance(typ, (StructType, TupleType)):
        if isinstance(typ, StructType):
            if not isinstance(key, str):
                raise TypeMismatchException("Expecting a member variable access; cannot access element %r" % key)
            if key not in typ.members:
                raise TypeMismatchException("Object does not have member variable %s" % key)
            subtype = typ.members[key]
            attrs = sorted(typ.members.keys())
    
            if key not in attrs:
                raise TypeMismatchException("Member %s not found. Only the following available: %s" % (expr.attr, " ".join(attrs)))
            index = attrs.index(key)
        else:
            if not isinstance(key, int):
                raise TypeMismatchException("Expecting a static index; cannot access element %r" % key)
            attrs = list(range(len(typ.members)))
            index = key
        if location == 'storage':
            return LLLnode.from_list(['add', ['sha3_32', parent], index],
                                     typ=subtype,
                                     location='storage')

        elif location == 'storage_prehashed':
            return LLLnode.from_list(['add', parent, index],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            offset = 0
            for i in range(index):
                offset += 32 * get_size_of_type(typ.members[attrs[i]])
            return LLLnode.from_list(['add', offset, parent],
                                     typ=typ.members[key],
                                     location='memory')
        else:
            raise TypeMismatchException("Not expecting a member variable access")
    elif isinstance(typ, (ListType, MappingType)):
        if isinstance(typ, ListType):
            subtype = typ.subtype
            sub = ['uclamplt', base_type_conversion(key, key.typ, BaseType('num')), typ.count]
        else:
            subtype = typ.valuetype
            sub = base_type_conversion(key, key.typ, typ.keytype)
        if location == 'storage':
           return LLLnode.from_list(['add', ['sha3_32', parent], sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'storage_prehashed':
           return LLLnode.from_list(['add', parent, sub],
                                     typ=subtype,
                                     location='storage')
        elif location == 'memory':
            if isinstance(typ, MappingType):
                raise TypeMismatchException("Can only have fixed-side arrays in memory, not mappings")
            offset = 32 * get_size_of_type(subtype)
            return LLLnode.from_list(['add', ['mul', offset, sub], parent],
                                      typ=subtype,
                                      location='memory')
        else:
            raise TypeMismatchException("Not expecting an array access")
    else:
        raise TypeMismatchException("Cannot access the child of a constant variable! %r" % typ)



# Parse an expression
def parse_expr(expr, context):
    if isinstance(expr, LLLnode):
        return expr
    # Numbers (integers or decimals)
    elif isinstance(expr, ast.Num):
        orignum = get_original_if_0x_prefixed(expr, context)
        if orignum is None and isinstance(expr.n, int):
            if not (-2**127 + 1 <= expr.n <= 2**127 - 1):
                raise InvalidLiteralException("Number out of range: "+str(expr.n), expr)
            return LLLnode.from_list(expr.n, typ=BaseType('num', None))
        elif isinstance(expr.n, float):
            numstring, num, den = get_number_as_fraction(expr, context)
            if not (-2**127 * den < num < 2**127 * den):
                raise InvalidLiteralException("Number out of range: "+numstring, expr)
            if DECIMAL_DIVISOR % den:
                raise InvalidLiteralException("Too many decimal places: "+numstring, expr)
            return LLLnode.from_list(num * DECIMAL_DIVISOR // den, typ=BaseType('decimal', None))
        elif len(orignum) == 42:
            if checksum_encode(orignum) != orignum:
                raise InvalidLiteralException("Address checksum mismatch. If you are sure this is the "
                                              "right address, the correct checksummed form is: "+
                                              checksum_encode(orignum), expr)
            return LLLnode.from_list(expr.n, typ=BaseType('address'))
        elif len(orignum) == 66:
            return LLLnode.from_list(expr.n, typ=BaseType('bytes32'))
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
        return LLLnode.from_list(['seq'] + seq + [placeholder], typ=ByteArrayType(len(bytez)), location='memory')
    # True, False, None constants
    elif isinstance(expr, ast.NameConstant):
        if expr.value == True:
            return LLLnode.from_list(1, typ='bool')
        elif expr.value == False:
            return LLLnode.from_list(0, typ='bool')
        elif expr.value == None:
            return LLLnode.from_list(None, typ=NullType())
        else:
            raise Exception("Unknown name constant: %r" % expr.value.value)
    # Variable names
    elif isinstance(expr, ast.Name):
        if expr.id == 'self':
            return LLLnode.from_list(['address'], typ='address')
        if expr.id == 'true':
            return LLLnode.from_list(1, typ='bool')
        if expr.id == 'false':
            return LLLnode.from_list(0, typ='bool')
        if expr.id == 'null':
            return LLLnode.from_list(None, typ=NullType())
        if expr.id in context.args:
            dataloc, typ = context.args[expr.id]
            if dataloc >= 0:
                data_decl = ['calldataload', dataloc]
            else:
                data_decl = ['seq', ['codecopy', FREE_VAR_SPACE, ['sub', ['codesize'], -dataloc], 32], ['mload', FREE_VAR_SPACE]]
            if is_base_type(typ, ('num', 'bool', 'decimal', 'address', 'num256', 'signed256', 'bytes32')):
                return LLLnode.from_list(data_decl, typ=typ)
            elif isinstance(typ, ByteArrayType):
                return LLLnode.from_list(data_decl, typ=typ, location='calldata')
            else:
                raise InvalidTypeException("Unsupported type: %r" % typ, expr)
        elif expr.id in context.vars:
            dataloc, typ = context.vars[expr.id]
            return LLLnode.from_list(dataloc, typ=typ, location='memory')
        else:
            raise VariableDeclarationException("Undeclared variable: "+expr.id, expr)
    # x.y or x[5]
    elif isinstance(expr, ast.Attribute):
        # x.balance: balance of address x
        if expr.attr == 'balance':
            addr = parse_value_expr(expr.value, context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException("Type mismatch: balance keyword expects an address as input", expr)
            return LLLnode.from_list(['balance', addr], typ=BaseType('num', {'wei': 1}), location=None)
        # self.x: global attribute
        elif isinstance(expr.value, ast.Name) and expr.value.id == "self":
            if expr.attr not in context.globals:
                raise VariableDeclarationException("Persistent variable undeclared: "+expr.attr, expr)
            pos, typ = context.globals[expr.attr][0],context.globals[expr.attr][1]
            return LLLnode.from_list(pos, typ=typ, location='storage')
        # Reserved keywords
        elif isinstance(expr.value, ast.Name) and expr.value.id in ("msg", "block", "tx"):
            key = expr.value.id + "." + expr.attr
            if key == "msg.sender":
                return LLLnode.from_list(['caller'], typ='address')
            elif key == "msg.value":
                return LLLnode.from_list(['callvalue'], typ=BaseType('num', {'wei': 1}))
            elif key == "block.difficulty":
                return LLLnode.from_list(['difficulty'], typ='num')
            elif key == "block.timestamp":
                return LLLnode.from_list(['timestamp'], typ=BaseType('num', {'sec': 1}, True))
            elif key == "block.coinbase":
                return LLLnode.from_list(['coinbase'], typ='address')
            elif key == "block.number":
                return LLLnode.from_list(['number'], typ='num')
            elif key == "block.prevhash":
                return LLLnode.from_list(['prevhash', ['sub', 'number', 1]], typ='bytes32')
            elif key == "tx.origin":
                return LLLnode.from_list(['origin'], typ='address')
            else:
                raise Exception("Unsupported keyword: "+key)
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
        return add_variable_offset(sub, index)
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
            new_positional = left.typ.positional ^ right.typ.positional # xor, as subtracting two positionals gives a delta
            op = 'add' if isinstance(expr.op, ast.Add) else 'sub'
            if ltyp == rtyp:
                o = LLLnode.from_list([op, left, right], typ=BaseType(ltyp, new_unit, new_positional))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right],
                                      typ=BaseType('decimal', new_unit, new_positional))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit, new_positional))
            else:
                raise Exception("How did I get here? %r %r" % (ltyp, rtyp))
        elif isinstance(expr.op, ast.Mult):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot multiply positional values!", expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit)
            if ltyp == rtyp == 'num':
                o = LLLnode.from_list(['mul', left, right], typ=BaseType('num', new_unit))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                ['sdiv', 'ans', DECIMAL_DIVISOR]]]]], typ=BaseType('decimal', new_unit))
            elif (ltyp == 'num' and rtyp == 'decimal') or (ltyp == 'decimal' and rtyp == 'num'):
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                'ans']]]], typ=BaseType('decimal', new_unit))
        elif isinstance(expr.op, ast.Div):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot divide positional values!", expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit, div=True)
            if rtyp == 'num':
                o = LLLnode.from_list(['sdiv', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'l', left, ['with', 'r', ['clamp_nonzero', right],
                                            ['sdiv', ['mul', 'l', DECIMAL_DIVISOR], 'r']]],
                                      typ=BaseType('decimal', new_unit))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['sdiv', ['mul', left, DECIMAL_DIVISOR ** 2], ['clamp_nonzero', right]],
                                      typ=BaseType('decimal', new_unit))
        elif isinstance(expr.op, ast.Mod):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot use positional values as modulus arguments!", expr)
            if left.typ.unit != right.typ.unit and left.typ.unit is not None and right.typ.unit is not None:
                raise TypeMismatchException("Modulus arguments must have same unit", expr)
            new_unit = left.typ.unit or right.typ.unit
            if ltyp == rtyp:
                o = LLLnode.from_list(['smod', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list(['smod', left, ['mul', ['clamp_nonzero', right], DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['smod', ['mul', left, DECIMAL_DIVISOR], right],
                                      typ=BaseType('decimal', new_unit))
        else:
            raise Exception("Unsupported binop: %r" % expr.op)
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
            o = LLLnode.from_list([op, left, right], typ='bool')
        elif ltyp == 'decimal' and rtyp == 'num':
            o = LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]], typ='bool')
        elif ltyp == 'num' and rtyp == 'decimal':
            o = LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right], typ='bool')
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
            raise Exception("Unsupported bool op: "+expr.op)
        o = LLLnode.from_list([op, left, right], typ='bool')
    # Unary operations (only "not" supported)
    elif isinstance(expr, ast.UnaryOp):
        operand = parse_value_expr(expr.operand, context)
        if isinstance(expr.op, ast.Not):
            # Note that in the case of bool, num, address, decimal, num256 AND bytes32,
            # a zero entry represents false, all others represent true
            o = LLLnode.from_list(["iszero", operand], typ='bool')
        elif isinstance(expr.op, ast.USub):
            if not is_numeric_type(operand.typ):
                raise TypeMismatchException("Unsupported type for negation: %r" % operand.typ, operand)
            o = LLLnode.from_list(["sub", 0, operand], typ=operand.typ)
        else:
            raise Exception("Only the 'not' unary operator is supported")
    # Function calls
    elif isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id in dispatch_table:
            return dispatch_table[expr.func.id](expr, context)
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
        return LLLnode.from_list(["multi"] + o, typ=ListType(out_type, len(o)))
    # Struct literals
    elif isinstance(expr, ast.Dict):
        o = {}
        members = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, ast.Name) or not is_varname_valid(key.id):
                raise TypeMismatchException("Invalid member variable for struct: %r" % vars(key).get('id', key), key)
            if key.id in o:
                raise TypeMismatchException("Member variable duplicated: "+key.id, key)
            o[key.id] = parse_expr(value, context)
            members[key.id] = o[key.id].typ
        return LLLnode.from_list(["multi"] + [o[key] for key in sorted(list(o.keys()))], typ=StructType(members))
    else:
        raise Exception("Unsupported operator: %r" % ast.dump(expr))
    # Clamp based on variable type
    if o.location is None and o.typ == 'bool':
        return o
    elif o.location is None and o.typ == 'num':
        return LLLnode.from_list(['clamp', ['mload', MINNUM_POS], o, ['mload', MAXNUM_POS]], typ='num')
    elif o.location is None and o.typ == 'decimal':
        return LLLnode.from_list(['clamp', ['mload', MINDECIMAL_POS], o, ['mload', MAXDECIMAL_POS]], typ='decimal')
    else:
        return o

# Unwrap location
def unwrap_location(orig):
    if orig.location == 'memory':
        return LLLnode.from_list(['mload', orig], typ=orig.typ)
    elif orig.location == 'storage':
        return LLLnode.from_list(['sload', orig], typ=orig.typ)
    elif orig.location == 'calldata':
        return LLLnode.from_list(['calldataload', orig], typ=orig.typ)
    else:
        return orig

# Parse an expression that represents an address in memory or storage
def parse_variable_location(expr, context):
    o = parse_expr(expr, context)
    if not o.location:
        raise Exception("Looking for a variable location, instead got a value")
    return o

# Parse an expression that results in a value
def parse_value_expr(expr, context):
    return unwrap_location(parse_expr(expr, context))

# Convert from one base type to another
def base_type_conversion(orig, frm, to):
    orig = unwrap_location(orig)
    if not isinstance(frm, (BaseType, NullType)) or not isinstance(to, BaseType):
        raise TypeMismatchException("Base type conversion from or to non-base type: %r %r" % (frm, to))
    elif is_base_type(frm, to.typ) and are_units_compatible(frm, to):
        return LLLnode(orig.value, orig.args, typ=to)
    elif is_base_type(frm, 'num') and is_base_type(to, 'decimal') and are_units_compatible(frm, to):
        return LLLnode.from_list(['mul', orig, DECIMAL_DIVISOR], typ=BaseType('decimal', to.unit, to.positional))
    elif isinstance(frm, NullType):
        if to.typ not in ('num', 'bool', 'num256', 'address', 'bytes32', 'decimal'):
            raise TypeMismatchException("Cannot convert null-type object to type %r" % to)
        return LLLnode.from_list(0, typ=to)
    else:
        raise TypeMismatchException("Typecasting from base type %r to %r unavailable" % (frm, to))

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
    if isinstance(stmt, ast.Expr):
        return parse_stmt(stmt.value, context)
    elif isinstance(stmt, ast.Pass):
        return LLLnode.from_list('pass', typ=None)
    elif isinstance(stmt, ast.AnnAssign):
        typ = parse_type(stmt.annotation, location='memory')
        varname = stmt.target.id
        pos = context.new_variable(varname, typ)
        return LLLnode.from_list('pass', typ=None)
    elif isinstance(stmt, ast.Assign):
        # Assignment (eg. x[4] = y)
        if len(stmt.targets) != 1:
            raise StructureException("Assignment statement must have one target", stmt)
        sub = parse_expr(stmt.value, context)
        if isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id not in context.vars:
            pos = context.new_variable(stmt.targets[0].id, set_default_units(sub.typ))
            return make_setter(LLLnode.from_list(pos, typ=sub.typ, location='memory'), sub, 'memory')
        else:
            target = parse_variable_location(stmt.targets[0], context)
            if target.location == 'storage' and context.is_constant:
                raise ConstancyViolationException("Cannot modify storage inside a constant function!", stmt.targets[0])
            return make_setter(target, sub, target.location)
    # If statements
    elif isinstance(stmt, ast.If):
        if stmt.orelse:
            return LLLnode.from_list(['if',
                                      parse_value_expr(stmt.test, context),
                                      parse_body(stmt.body, context),
                                      parse_body(stmt.orelse, context)], typ=None)
        else:
            return LLLnode.from_list(['if',
                                      parse_value_expr(stmt.test, context),
                                      parse_body(stmt.body, context)], typ=None)
    # Calls
    elif isinstance(stmt, ast.Call):
        if isinstance(stmt.func, ast.Name) and stmt.func.id in stmt_dispatch_table:
            return stmt_dispatch_table[stmt.func.id](stmt, context)
        else:
            raise StructureException("Unsupported operator: %r" % ast.dump(stmt), stmt)
    # Asserts
    elif isinstance(stmt, ast.Assert):
        return LLLnode.from_list(['assert', parse_value_expr(stmt.test, context)], typ=None)
    # for i in range(n): ... (note: n must be a nonzero positive constant integer)
    elif isinstance(stmt, ast.For):
        if not isinstance(stmt.iter, ast.Call) or \
                not isinstance(stmt.iter.func, ast.Name) or \
                not isinstance(stmt.target, ast.Name) or \
                stmt.iter.func.id != "range" or \
                len(stmt.iter.args) not in (1, 2):
            raise StructureException("For statements must be of the form `for i in range(rounds): ..` or `for i in range(start, start + rounds): ..`", stmt.iter)
        # Type 1 for, eg. for i in range(10): ...
        if len(stmt.iter.args) == 1:
            if not isinstance(stmt.iter.args[0], ast.Num):
                raise StructureException("Repeat must have a nonzero positive integral number of rounds", stmt.iter)
            start = LLLnode.from_list(0, typ='num')
            rounds = stmt.iter.args[0].n
        elif len(stmt.iter.args) == 2:
            if isinstance(stmt.iter.args[0], ast.Num) and isinstance(stmt.iter.args[1], ast.Num):
                # Type 2 for, eg. for i in range(100, 110): ...
                start = LLLnode.from_list(stmt.iter.args[0].n, typ='num')
                rounds = LLLnode.from_list(stmt.iter.args[1].n - stmt.iter.args[0].n, typ='num')
            else:
                # Type 3 for, eg. for i in range(x, x + 10): ...
                if not isinstance(stmt.iter.args[1], ast.BinOp) or not isinstance(stmt.iter.args[1].op, ast.Add):
                    raise StructureException("Two-arg for statements must be of the form `for i in range(start, start + rounds): ...`",
                                             stmt.iter.args[1])
                if ast.dump(stmt.iter.args[0]) != ast.dump(stmt.iter.args[1].left):
                    raise StructureException("Two-arg for statements of the form `for i in range(x, x + y): ...` must have x identical in both places: %r %r" % (ast.dump(stmt.iter.args[0]), ast.dump(stmt.iter.args[1].left)), stmt.iter)
                if not isinstance(stmt.iter.args[1].right, ast.Num):
                    raise StructureException("Repeat must have a nonzero positive integral number of rounds", stmt.iter.args[1])
                start = parse_value_expr(stmt.iter.args[0], context)
                rounds = stmt.iter.args[1].right.n
        varname = stmt.target.id
        pos = context.vars[varname][0] if varname in context.forvars else context.new_variable(varname, BaseType('num'))
        o = LLLnode.from_list(['repeat', pos, start, rounds, parse_body(stmt.body, context)], typ=None)
        context.forvars[varname] = True
        return o
    # Creating a new memory variable and assigning it
    elif isinstance(stmt, ast.AugAssign):
        target = parse_variable_location(stmt.target, context)
        sub = parse_value_expr(stmt.value, context)
        #sub = base_type_conversion(sub, sub.typ, target.typ)
        if not isinstance(stmt.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            raise Exception("Unsupported operator for augassign")
        if not isinstance(target.typ, BaseType):
            raise TypeMismatchException("Can only use aug-assign operators with simple types!", stmt.target)
        if target.location == 'storage':
            if context.is_constant:
                raise ConstancyViolationException("Cannot modify storage inside a constant function!", stmt.target)
            o = parse_value_expr(ast.BinOp(left=LLLnode.from_list(['sload', '_addr'], typ=target.typ),
                                 right=sub, op=stmt.op), context)
            return LLLnode.from_list(['with', '_addr', target, ['sstore', '_addr', base_type_conversion(o, o.typ, target.typ)]], typ=None)
        elif target.location == 'memory':
            o = parse_value_expr(ast.BinOp(left=LLLnode.from_list(['mload', '_addr'], typ=target.typ),
                                 right=sub, op=stmt.op), context)
            return LLLnode.from_list(['with', '_addr', target, ['mstore', '_addr', base_type_conversion(o, o.typ, target.typ)]], typ=None)
    # Break from a loop
    elif isinstance(stmt, ast.Break):
        return LLLnode.from_list('break', typ=None)
    # Return statement
    elif isinstance(stmt, ast.Return):
        if context.return_type is None:
            if stmt.value:
                raise TypeMismatchException("Not expecting to return a value", stmt)
            return LLLnode.from_list(['return', 0, 0], typ=None)
        if not stmt.value:
            raise TypeMismatchException("Expecting to return a value", stmt)
        sub = parse_expr(stmt.value, context)
        # Returning a value (most common case)
        if isinstance(sub.typ, BaseType):
            if not isinstance(context.return_type, BaseType):
                raise TypeMismatchException("Trying to return base type %r, output expecting %r" % (sub.typ, context.return_type), stmt.value)
            sub = unwrap_location(sub)
            if not are_units_compatible(sub.typ, context.return_type):
                raise TypeMismatchException("Return type units mismatch %r %r" % (sub.typ, context.return_type), stmt.value)
            elif is_base_type(sub.typ, context.return_type.typ) or \
                    (is_base_type(sub.typ, 'num') and is_base_type(context.return_type, 'signed256')):
                return LLLnode.from_list(['seq', ['mstore', 0, sub], ['return', 0, 32]], typ=None)
            elif is_base_type(sub.typ, 'num') and is_base_type(context.return_type, 'num256'):
                return LLLnode.from_list(['seq', ['mstore', 0, sub],
                                                 ['assert', ['sge', ['mload', 0], 0]],
                                                 ['return', 0, 32]], typ=None)
            else:
                raise TypeMismatchException("Unsupported type conversion: %r to %r" % (sub.typ, context.return_type), stmt.value)
        # Returning a byte array
        elif isinstance(sub.typ, ByteArrayType):
            if not isinstance(context.return_type, ByteArrayType):
                raise TypeMismatchException("Trying to return base type %r, output expecting %r" % (sub.typ, context.return_type), stmt.value)
            if sub.typ.maxlen > context.return_type.maxlen:
                raise TypeMismatchException("Cannot cast from greater max-length %d to shorter max-length %d" %
                                            (sub.typ.maxlen, context.return_type.maxlen), stmt.value)
            # Copying from calldata
            if sub.location == 'calldata':
                return LLLnode.from_list(['with', '_pos', ['add', 4, sub],
                                            ['with', '_len', ['ceil32', ['add', ['calldataload', '_pos'], 32]],
                                                    ['seq', ['assert', ['le', ['calldataload', '_pos'], sub.typ.maxlen]],
                                                            ['mstore', context.get_next_mem(), 32],
                                                            ['calldatacopy', context.get_next_mem() + 32, '_pos', '_len'],
                                                            ['return', context.get_next_mem(), ['add', '_len', 32]]]]], typ=None)
            # Returning something already in memory
            elif sub.location == 'memory':
                return LLLnode.from_list(['with', '_loc', sub,
                                            ['seq',
                                                ['mstore', ['sub', '_loc', 32], 32],
                                                ['return', ['sub', '_loc', 32], ['ceil32', ['add', ['mload', '_loc'], 64]]]]], typ=None)
            # Copying from storage
            elif sub.location == 'storage':
                # Instantiate a byte array at some index
                fake_byte_array = LLLnode(context.get_next_mem() + 32, typ=sub.typ, location='memory')
                o = ['seq',
                        # Copy the data to this byte array
                        make_byte_array_copier(fake_byte_array, sub),
                        # Store the number 32 before it for ABI formatting purposes
                        ['mstore', context.get_next_mem(), 32],
                        # Return it
                        ['return', context.get_next_mem(), ['add', ['ceil32', ['mload', context.get_next_mem() + 32]], 64]]]
                return LLLnode.from_list(o, typ=None)
            else:
                raise Exception("Invalid location: %s" % sub.location)
        else:
            raise TypeMismatchException("Can only return base type!", stmt)
    else:
        raise StructureException("Unsupported statement type", stmt)
