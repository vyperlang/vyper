import warnings

from vyper import ast
from vyper.exceptions import (
    InvalidLiteralException,
    NonPayableViolationException,
    ParserException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)
from vyper.parser import (
    external_call,
    self_call,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    add_variable_offset,
    get_number_as_fraction,
    get_original_if_0_prefixed,
    getpos,
    make_setter,
    unwrap_location,
)
from vyper.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ContractType,
    ListType,
    MappingType,
    NullType,
    StringType,
    StructType,
    TupleType,
    are_units_compatible,
    combine_units,
    is_base_type,
    is_numeric_type,
)
from vyper.utils import (
    DECIMAL_DIVISOR,
    MemoryPositions,
    SizeLimits,
    bytes_to_int,
    check_valid_varname,
    checksum_encode,
    string_to_bytes,
)


class Expr(object):
    # TODO: Once other refactors are made reevaluate all inline imports
    def __init__(self, expr, context):
        self.expr = expr
        self.context = context
        self.expr_table = {
            LLLnode: self.get_expr,
            ast.Num: self.number,
            ast.Str: self.string,
            ast.NameConstant: self.constants,
            ast.Name: self.variables,
            ast.Attribute: self.attribute,
            ast.Subscript: self.subscript,
            ast.BinOp: self.arithmetic,
            ast.Compare: self.compare,
            ast.BoolOp: self.boolean_operations,
            ast.UnaryOp: self.unary_operations,
            ast.Call: self.call,
            ast.List: self.list_literals,
            ast.Tuple: self.tuple_literals,
            ast.Dict: self.dict_fail,
            ast.Bytes: self.bytes,
        }
        expr_type = self.expr.__class__
        if expr_type in self.expr_table:
            self.lll_node = self.expr_table[expr_type]()
        else:
            raise Exception("Unsupported operator.", self.expr)

    def get_expr(self):
        return self.expr

    def number(self):
        orignum = get_original_if_0_prefixed(self.expr, self.context)

        if orignum is None and isinstance(self.expr.n, int):
            # Literal (mostly likely) becomes int128
            if SizeLimits.in_bounds('int128', self.expr.n) or self.expr.n < 0:
                return LLLnode.from_list(
                    self.expr.n,
                    typ=BaseType('int128', unit={}, is_literal=True),
                    pos=getpos(self.expr),
                )
            # Literal is large enough (mostly likely) becomes uint256.
            else:
                return LLLnode.from_list(
                    self.expr.n,
                    typ=BaseType('uint256', unit={}, is_literal=True),
                    pos=getpos(self.expr),
                )

        elif isinstance(self.expr.n, float):
            numstring, num, den = get_number_as_fraction(self.expr, self.context)
            # if not SizeLimits.in_bounds('decimal', num // den):
            # if not SizeLimits.MINDECIMAL * den <= num <= SizeLimits.MAXDECIMAL * den:
            if not (SizeLimits.MINNUM * den < num < SizeLimits.MAXNUM * den):
                raise InvalidLiteralException("Number out of range: " + numstring, self.expr)
            if DECIMAL_DIVISOR % den:
                raise InvalidLiteralException("Too many decimal places: " + numstring, self.expr)
            return LLLnode.from_list(
                num * DECIMAL_DIVISOR // den,
                typ=BaseType('decimal', unit=None, is_literal=True),
                pos=getpos(self.expr),
            )

        # Binary literal.
        elif orignum[:2] == '0b':
            str_val = orignum[2:]
            total_bits = len(orignum[2:])
            total_bits = (
                total_bits
                if total_bits % 8 == 0
                else total_bits + 8 - (total_bits % 8)  # ceil8 to get byte length.
            )
            if len(orignum[2:]) != total_bits:  # Support only full formed bit definitions.
                raise InvalidLiteralException((
                    "Bit notation requires a multiple of 8 bits / 1 byte. {} "
                    "bit(s) are missing."
                ).format(total_bits - len(orignum[2:])), self.expr)
            byte_len = int(total_bits / 8)
            placeholder = self.context.new_placeholder(ByteArrayType(byte_len))
            seq = []
            seq.append(['mstore', placeholder, byte_len])
            for i in range(0, total_bits, 256):
                section = str_val[i:i + 256]
                int_val = int(section, 2) << (256 - len(section))  # bytes are right padded.
                seq.append(
                    ['mstore', ['add', placeholder, i + 32], int_val])
            return LLLnode.from_list(
                ['seq'] + seq + [placeholder],
                typ=ByteArrayType(byte_len),
                location='memory',
                pos=getpos(self.expr),
                annotation='Create ByteArray (Binary literal): %s' % str_val,
            )
        elif len(orignum) == 42:
            if checksum_encode(orignum) != orignum:
                raise InvalidLiteralException("""Address checksum mismatch. If you are sure this is the
right address, the correct checksummed form is: %s""" % checksum_encode(orignum), self.expr)
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType('address', is_literal=True),
                pos=getpos(self.expr),
            )
        elif len(orignum) == 66:
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType('bytes32', is_literal=True),
                pos=getpos(self.expr),
            )
        else:
            raise InvalidLiteralException((
                "Cannot read 0x value with length %d. Expecting 42 (address "
                "incl 0x) or 66 (bytes32 incl 0x)"
            ) % len(orignum), self.expr)

    # String literals
    def string(self):
        bytez, bytez_length = string_to_bytes(self.expr.s)
        return self._make_bytelike(StringType(bytez_length), bytez, bytez_length)

    # Byte literals
    def bytes(self):
        bytez = self.expr.s
        bytez_length = len(self.expr.s)
        return self._make_bytelike(ByteArrayType(bytez_length), bytez, bytez_length)

    def _make_bytelike(self, btype, bytez, bytez_length):
        placeholder = self.context.new_placeholder(btype)
        seq = []
        seq.append(['mstore', placeholder, bytez_length])
        for i in range(0, len(bytez), 32):
            seq.append([
                'mstore',
                ['add', placeholder, i + 32],
                bytes_to_int((bytez + b'\x00' * 31)[i: i + 32])
            ])
        return LLLnode.from_list(
            ['seq'] + seq + [placeholder],
            typ=btype,
            location='memory',
            pos=getpos(self.expr),
            annotation='Create %r: %s' % (btype, bytez),
        )

    # True, False, None constants
    def constants(self):
        if self.expr.value is True:
            return LLLnode.from_list(
                1,
                typ=BaseType('bool', is_literal=True),
                pos=getpos(self.expr),
            )
        elif self.expr.value is False:
            return LLLnode.from_list(
                0,
                typ=BaseType('bool', is_literal=True),
                pos=getpos(self.expr),
            )
        elif self.expr.value is None:
            return LLLnode.from_list(None, typ=NullType(), pos=getpos(self.expr))
        else:
            raise Exception("Unknown name constant: %r" % self.expr.value.value)

    # Variable names
    def variables(self):
        builtin_constants = {
            'EMPTY_BYTES32': LLLnode.from_list(
                [0],
                typ=BaseType('bytes32', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'ZERO_ADDRESS': LLLnode.from_list(
                [0],
                typ=BaseType('address', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'MAX_INT128': LLLnode.from_list(
                [SizeLimits.MAXNUM],
                typ=BaseType('int128', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'MIN_INT128': LLLnode.from_list(
                [SizeLimits.MINNUM],
                typ=BaseType('int128', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'MAX_DECIMAL': LLLnode.from_list(
                [SizeLimits.MAXDECIMAL],
                typ=BaseType('decimal', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'MIN_DECIMAL': LLLnode.from_list(
                [SizeLimits.MINDECIMAL],
                typ=BaseType('decimal', None, is_literal=True),
                pos=getpos(self.expr)
            ),
            'MAX_UINT256': LLLnode.from_list(
                [SizeLimits.MAX_UINT256],
                typ=BaseType('uint256', None, is_literal=True),
                pos=getpos(self.expr)
            ),
        }

        if self.expr.id == 'self':
            return LLLnode.from_list(['address'], typ='address', pos=getpos(self.expr))
        elif self.expr.id in self.context.vars:
            var = self.context.vars[self.expr.id]
            return LLLnode.from_list(
                var.pos,
                typ=var.typ,
                location='memory',
                pos=getpos(self.expr),
                annotation=self.expr.id,
                mutable=var.mutable,
            )
        elif self.expr.id in builtin_constants:
            return builtin_constants[self.expr.id]
        elif self.context.constants.ast_is_constant(self.expr):
            return self.context.constants.get_constant(self.expr.id, self.context)
        else:
            raise VariableDeclarationException("Undeclared variable: " + self.expr.id, self.expr)

    # x.y or x[5]
    def attribute(self):
        # x.balance: balance of address x
        if self.expr.attr == 'balance':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException(
                    "Type mismatch: balance keyword expects an address as input",
                    self.expr
                )
            return LLLnode.from_list(
                ['balance', addr],
                typ=BaseType('uint256', {'wei': 1}),
                location=None,
                pos=getpos(self.expr),
            )
        # x.codesize: codesize of address x
        elif self.expr.attr == 'codesize' or self.expr.attr == 'is_contract':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException(
                    "Type mismatch: codesize keyword expects an address as input",
                    self.expr,
                )
            if self.expr.attr == 'codesize':
                eval_code = ['extcodesize', addr]
                output_type = 'int128'
            else:
                eval_code = ['gt', ['extcodesize', addr], 0]
                output_type = 'bool'
            return LLLnode.from_list(
                eval_code,
                typ=BaseType(output_type),
                location=None,
                pos=getpos(self.expr),
            )
        # self.x: global attribute
        elif isinstance(self.expr.value, ast.Name) and self.expr.value.id == "self":
            if self.expr.attr not in self.context.globals:
                raise VariableDeclarationException(
                    "Persistent variable undeclared: " + self.expr.attr,
                    self.expr,
                )
            var = self.context.globals[self.expr.attr]
            return LLLnode.from_list(
                var.pos,
                typ=var.typ,
                location='storage',
                pos=getpos(self.expr),
                annotation='self.' + self.expr.attr,
            )
        # Reserved keywords
        elif isinstance(self.expr.value, ast.Name) and self.expr.value.id in ("msg", "block", "tx"):
            key = self.expr.value.id + "." + self.expr.attr
            if key == "msg.sender":
                if self.context.is_private:
                    raise ParserException("msg.sender not allowed in private functions.", self.expr)
                return LLLnode.from_list(['caller'], typ='address', pos=getpos(self.expr))
            elif key == "msg.value":
                if not self.context.is_payable:
                    raise NonPayableViolationException(
                        "Cannot use msg.value in a non-payable function", self.expr,
                    )
                return LLLnode.from_list(
                    ['callvalue'],
                    typ=BaseType('uint256', {'wei': 1}),
                    pos=getpos(self.expr),
                )
            elif key == "msg.gas":
                return LLLnode.from_list(
                    ['gas'],
                    typ='uint256',
                    pos=getpos(self.expr),
                )
            elif key == "block.difficulty":
                return LLLnode.from_list(
                    ['difficulty'],
                    typ='uint256',
                    pos=getpos(self.expr),
                )
            elif key == "block.timestamp":
                return LLLnode.from_list(
                    ['timestamp'],
                    typ=BaseType('uint256', {'sec': 1}, True),
                    pos=getpos(self.expr),
                )
            elif key == "block.coinbase":
                return LLLnode.from_list(['coinbase'], typ='address', pos=getpos(self.expr))
            elif key == "block.number":
                return LLLnode.from_list(['number'], typ='uint256', pos=getpos(self.expr))
            elif key == "block.prevhash":
                return LLLnode.from_list(
                    ['blockhash', ['sub', 'number', 1]],
                    typ='bytes32',
                    pos=getpos(self.expr),
                )
            elif key == "tx.origin":
                return LLLnode.from_list(['origin'], typ='address', pos=getpos(self.expr))
            else:
                raise ParserException("Unsupported keyword: " + key, self.expr)
        # Other variables
        else:
            sub = Expr.parse_variable_location(self.expr.value, self.context)
            # contract type
            if isinstance(sub.typ, ContractType):
                return sub
            if not isinstance(sub.typ, StructType):
                raise TypeMismatchException(
                    "Type mismatch: member variable access not expected",
                    self.expr.value,
                )
            attrs = list(sub.typ.members.keys())
            if self.expr.attr not in attrs:
                raise TypeMismatchException(
                    "Member %s not found. Only the following available: %s" % (
                        self.expr.attr, " ".join(attrs)
                    ),
                    self.expr,
                )
            return add_variable_offset(sub, self.expr.attr, pos=getpos(self.expr))

    def subscript(self):
        sub = Expr.parse_variable_location(self.expr.value, self.context)
        if isinstance(sub.typ, (MappingType, ListType)):
            if not isinstance(self.expr.slice, ast.Index):
                raise StructureException(
                    "Array access must access a single element, not a slice",
                    self.expr,
                )
            index = Expr.parse_value_expr(self.expr.slice.value, self.context)
        elif isinstance(sub.typ, TupleType):
            if not isinstance(self.expr.slice.value, ast.Num) or self.expr.slice.value.n < 0 or self.expr.slice.value.n >= len(sub.typ.members):  # noqa: E501
                raise TypeMismatchException("Tuple index invalid", self.expr.slice.value)
            index = self.expr.slice.value.n
        else:
            raise TypeMismatchException("Bad subscript attempt", self.expr.value)
        o = add_variable_offset(sub, index, pos=getpos(self.expr))
        o.mutable = sub.mutable
        return o

    def arithmetic_get_reference(self, item):
        item_lll = Expr.parse_value_expr(item, self.context)
        if item_lll.typ is None:
            raise TypeMismatchException(
                'Arithmetic can not be performed on None (return) type.',
                self.expr,
            )
        if isinstance(item, ast.Call):
            # Perform call statements once.
            placeholder = self.context.new_placeholder(item_lll.typ)
            pre_alloc = ['mstore', placeholder, item_lll]
            return (
                pre_alloc,
                LLLnode.from_list(['mload', placeholder], location='memory', typ=item_lll.typ),
            )
        else:
            return None, item_lll

    def arithmetic(self):
        pre_alloc_left, left = self.arithmetic_get_reference(self.expr.left)
        pre_alloc_right, right = self.arithmetic_get_reference(self.expr.right)

        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            raise TypeMismatchException(
                "Unsupported types for arithmetic op: %r %r" % (left.typ, right.typ),
                self.expr,
            )

        arithmetic_pair = {left.typ.typ, right.typ.typ}

        # Special Case: Simplify any literal to literal arithmetic at compile time.
        if left.typ.is_literal and right.typ.is_literal and \
           isinstance(right.value, int) and isinstance(left.value, int) and \
           arithmetic_pair.issubset({'uint256', 'int128'}):

            if isinstance(self.expr.op, ast.Add):
                val = left.value + right.value
            elif isinstance(self.expr.op, ast.Sub):
                val = left.value - right.value
            elif isinstance(self.expr.op, ast.Mult):
                val = left.value * right.value
            elif isinstance(self.expr.op, ast.Div):
                val = left.value // right.value
            elif isinstance(self.expr.op, ast.Mod):
                val = left.value % right.value
            elif isinstance(self.expr.op, ast.Pow):
                val = left.value ** right.value
            else:
                raise ParserException(
                    'Unsupported literal operator: %s' % str(type(self.expr.op)),
                    self.expr,
                )

            num = ast.Num(n=val)
            num.source_code = self.expr.source_code
            num.lineno = self.expr.lineno
            num.col_offset = self.expr.col_offset

            return Expr.parse_value_expr(num, self.context)

        # Special case with uint256 were int literal may be casted.
        if arithmetic_pair == {'uint256', 'int128'}:
            # Check right side literal.
            if right.typ.is_literal and SizeLimits.in_bounds('uint256', right.value):
                right = LLLnode.from_list(
                    right.value,
                    typ=BaseType('uint256', None, is_literal=True),
                    pos=getpos(self.expr),
                )

            # Check left side literal.
            elif left.typ.is_literal and SizeLimits.in_bounds('uint256', left.value):
                left = LLLnode.from_list(
                    left.value,
                    typ=BaseType('uint256', None, is_literal=True),
                    pos=getpos(self.expr),
                )

        # Only allow explicit conversions to occur.
        if left.typ.typ != right.typ.typ:
            raise TypeMismatchException(
                "Cannot implicitly convert {} to {}.".format(left.typ.typ, right.typ.typ),
                self.expr,
            )

        ltyp, rtyp = left.typ.typ, right.typ.typ
        if isinstance(self.expr.op, (ast.Add, ast.Sub)):
            if left.typ.unit != right.typ.unit and left.typ.unit != {} and right.typ.unit != {}:
                raise TypeMismatchException(
                    "Unit mismatch: %r %r" % (left.typ.unit, right.typ.unit),
                    self.expr,
                )
            if left.typ.positional and right.typ.positional and isinstance(self.expr.op, ast.Add):
                raise TypeMismatchException(
                    "Cannot add two positional units!",
                    self.expr,
                )
            new_unit = left.typ.unit or right.typ.unit

            # xor, as subtracting two positionals gives a delta
            new_positional = left.typ.positional ^ right.typ.positional

            op = 'add' if isinstance(self.expr.op, ast.Add) else 'sub'
            if ltyp == 'uint256' and isinstance(self.expr.op, ast.Add):
                o = LLLnode.from_list([
                    'seq',
                    # Checks that: a + b >= a
                    ['assert', ['ge', ['add', left, right], left]],
                    ['add', left, right],
                ], typ=BaseType('uint256', new_unit, new_positional), pos=getpos(self.expr))
            elif ltyp == 'uint256' and isinstance(self.expr.op, ast.Sub):
                o = LLLnode.from_list([
                    'seq',
                    # Checks that: a >= b
                    ['assert', ['ge', left, right]],
                    ['sub', left, right]
                ], typ=BaseType('uint256', new_unit, new_positional), pos=getpos(self.expr))
            elif ltyp == rtyp:
                o = LLLnode.from_list(
                    [op, left, right],
                    typ=BaseType(ltyp, new_unit, new_positional),
                    pos=getpos(self.expr),
                )
            else:
                raise Exception("Unsupported Operation '%r(%r, %r)'" % (op, ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Mult):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot multiply positional values!", self.expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit)
            if ltyp == rtyp == 'uint256':
                o = LLLnode.from_list([
                    'if',
                    ['eq', left, 0],
                    [0],
                    [
                        'seq', ['assert', ['eq', ['div', ['mul', left, right], left], right]],
                        ['mul', left, right]
                    ],
                ], typ=BaseType('uint256', new_unit), pos=getpos(self.expr))
            elif ltyp == rtyp == 'int128':
                o = LLLnode.from_list(
                    ['mul', left, right],
                    typ=BaseType('int128', new_unit),
                    pos=getpos(self.expr),
                )
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list([
                    'with', 'r', right, [
                        'with', 'l', left, [
                            'with', 'ans', ['mul', 'l', 'r'],
                            [
                                'seq',
                                [
                                    'assert',
                                    ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['iszero', 'l']]
                                ],
                                ['sdiv', 'ans', DECIMAL_DIVISOR],
                            ],
                        ],
                    ],
                ], typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation 'mul(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Div):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot divide positional values!", self.expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit, div=True)
            if ltyp == rtyp == 'uint256':
                o = LLLnode.from_list([
                    'seq',
                    # Checks that:  b != 0
                    ['assert', right],
                    ['div', left, right],
                ], typ=BaseType('uint256', new_unit), pos=getpos(self.expr))
            elif ltyp == rtyp == 'int128':
                o = LLLnode.from_list(
                    ['sdiv', left, ['clamp_nonzero', right]],
                    typ=BaseType('int128', new_unit),
                    pos=getpos(self.expr),
                )
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list([
                    'with', 'l', left, [
                        'with', 'r', ['clamp_nonzero', right], [
                            'sdiv',
                            ['mul', 'l', DECIMAL_DIVISOR],
                            'r',
                        ],
                    ]
                ], typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation 'div(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Mod):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException(
                    "Cannot use positional values as modulus arguments!",
                    self.expr,
                )
            if not are_units_compatible(left.typ, right.typ) and not (left.typ.unit or right.typ.unit):  # noqa: E501
                raise TypeMismatchException("Modulus arguments must have same unit", self.expr)
            new_unit = left.typ.unit or right.typ.unit
            if ltyp == rtyp == 'uint256':
                o = LLLnode.from_list([
                    'seq',
                    ['assert', right],
                    ['mod', left, right]
                ], typ=BaseType('uint256', new_unit), pos=getpos(self.expr))
            elif ltyp == rtyp:
                o = LLLnode.from_list(
                    ['smod', left, ['clamp_nonzero', right]],
                    typ=BaseType(ltyp, new_unit),
                    pos=getpos(self.expr),
                )
            else:
                raise Exception("Unsupported Operation 'mod(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Pow):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException(
                    "Cannot use positional values as exponential arguments!",
                    self.expr,
                )
            if right.typ.unit:
                raise TypeMismatchException(
                    "Cannot use unit values as exponents",
                    self.expr,
                )
            if ltyp != 'int128' and ltyp != 'uint256' and isinstance(self.expr.right, ast.Name):
                raise TypeMismatchException(
                    "Cannot use dynamic values as exponents, for unit base types",
                    self.expr,
                )
            if ltyp == rtyp == 'uint256':
                o = LLLnode.from_list([
                    'seq',
                    [
                        'assert',
                        [
                            'or',
                            ['or', ['eq', right, 1], ['iszero', right]],
                            ['lt', left, ['exp', left, right]]
                        ],
                    ],
                    ['exp', left, right],
                ], typ=BaseType('uint256'), pos=getpos(self.expr))
            elif ltyp == rtyp == 'int128':
                new_unit = left.typ.unit
                if left.typ.unit and not isinstance(self.expr.right, ast.Name):
                    new_unit = {left.typ.unit.copy().popitem()[0]: self.expr.right.n}
                o = LLLnode.from_list(
                    ['exp', left, right],
                    typ=BaseType('int128', new_unit),
                    pos=getpos(self.expr),
                )
            else:
                raise TypeMismatchException('Only whole number exponents are supported', self.expr)
        else:
            raise ParserException("Unsupported binary operator: %r" % self.expr.op, self.expr)

        p = ['seq']

        if pre_alloc_left:
            p.append(pre_alloc_left)
        if pre_alloc_right:
            p.append(pre_alloc_right)

        if o.typ.typ == 'int128':
            p.append([
                'clamp',
                ['mload', MemoryPositions.MINNUM],
                o,
                ['mload', MemoryPositions.MAXNUM],
            ])
            return LLLnode.from_list(p, typ=o.typ, pos=getpos(self.expr))
        elif o.typ.typ == 'decimal':
            p.append([
                'clamp',
                ['mload', MemoryPositions.MINDECIMAL],
                o,
                ['mload', MemoryPositions.MAXDECIMAL],
            ])
            return LLLnode.from_list(p, typ=o.typ, pos=getpos(self.expr))
        if o.typ.typ == 'uint256':
            p.append(o)
            return LLLnode.from_list(p, typ=o.typ, pos=getpos(self.expr))
        else:
            raise Exception("%r %r" % (o, o.typ))

    def build_in_comparator(self):
        left = Expr(self.expr.left, self.context).lll_node
        right = Expr(self.expr.comparators[0], self.context).lll_node

        if left.typ != right.typ.subtype:
            raise TypeMismatchException(
                "%s cannot be in a list of %s" % (left.typ, right.typ.subtype),
            )

        result_placeholder = self.context.new_placeholder(BaseType('bool'))
        setter = []

        # Load nth item from list in memory.
        if right.value == 'multi':
            # Copy literal to memory to be compared.
            tmp_list = LLLnode.from_list(
                obj=self.context.new_placeholder(ListType(right.typ.subtype, right.typ.count)),
                typ=ListType(right.typ.subtype, right.typ.count),
                location='memory'
            )
            setter = make_setter(tmp_list, right, 'memory', pos=getpos(self.expr))
            load_i_from_list = [
                'mload',
                ['add', tmp_list, ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]],
            ]
        elif right.location == "storage":
            load_i_from_list = [
                'sload',
                ['add', ['sha3_32', right], ['mload', MemoryPositions.FREE_LOOP_INDEX]],
            ]
        else:
            load_i_from_list = [
                'mload',
                ['add', right, ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]],
            ]

        # Condition repeat loop has to break on.
        break_loop_condition = [
            'if',
            ['eq', unwrap_location(left), load_i_from_list],
            ['seq',
                ['mstore', '_result', 1],  # store true.
                'break']
        ]

        # Repeat loop to loop-compare each item in the list.
        for_loop_sequence = [
            ['mstore', result_placeholder, 0],
            ['with', '_result', result_placeholder, [
                'repeat',
                MemoryPositions.FREE_LOOP_INDEX,
                0,
                right.typ.count,
                break_loop_condition,
            ]],
            ['mload', result_placeholder]
        ]

        # Save list to memory, so one can iterate over it,
        # used when literal was created with tmp_list.
        if setter:
            compare_sequence = ['seq', setter] + for_loop_sequence
        else:
            compare_sequence = ['seq'] + for_loop_sequence

        # Compare the result of the repeat loop to 1, to know if a match was found.
        o = LLLnode.from_list([
            'eq', 1,
            compare_sequence],
            typ='bool',
            annotation="in comporator"
        )

        return o

    @staticmethod
    def _signed_to_unsigned_comparision_op(op):
        translation_map = {
            'sgt': 'gt',
            'sge': 'ge',
            'sle': 'le',
            'slt': 'lt',
        }
        if op in translation_map:
            return translation_map[op]
        else:
            return op

    def compare(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.comparators[0], self.context)

        if isinstance(right.typ, NullType):
            raise InvalidLiteralException(
                'Comparison to None is not allowed, compare against a default value.',
                self.expr,
            )

        if isinstance(left.typ, ByteArrayLike) and isinstance(right.typ, ByteArrayLike):
            if left.typ.maxlen != right.typ.maxlen:
                raise TypeMismatchException(
                    'Can only compare strings or bytes of the same length, shorter than 32 bytes.',
                    self.expr
                )
            if left.typ.maxlen > 32 or right.typ.maxlen > 32:
                raise ParserException(
                    'Can only compare strings/bytes of length shorter than 32 bytes',
                    self.expr,
                )
        elif isinstance(self.expr.ops[0], ast.In) and isinstance(right.typ, ListType):
            if left.typ != right.typ.subtype:
                raise TypeMismatchException(
                    "Can't use IN comparison with different types!",
                    self.expr,
                )
            return self.build_in_comparator()
        else:
            if not are_units_compatible(left.typ, right.typ) and not are_units_compatible(right.typ, left.typ):  # noqa: E501
                raise TypeMismatchException("Can't compare values with different units!", self.expr)

        if len(self.expr.ops) != 1:
            raise StructureException(
                "Cannot have a comparison with more than two elements",
                self.expr,
            )
        if isinstance(self.expr.ops[0], ast.Gt):
            op = 'sgt'
        elif isinstance(self.expr.ops[0], ast.GtE):
            op = 'sge'
        elif isinstance(self.expr.ops[0], ast.LtE):
            op = 'sle'
        elif isinstance(self.expr.ops[0], ast.Lt):
            op = 'slt'
        elif isinstance(self.expr.ops[0], ast.Eq):
            op = 'eq'
        elif isinstance(self.expr.ops[0], ast.NotEq):
            op = 'ne'
        else:
            raise Exception("Unsupported comparison operator")

        # Compare (limited to 32) byte arrays.
        if isinstance(left.typ, ByteArrayLike) and isinstance(left.typ, ByteArrayLike):
            left = Expr(self.expr.left, self.context).lll_node
            right = Expr(self.expr.comparators[0], self.context).lll_node

            def load_bytearray(side):
                if side.location == 'memory':
                    return ['mload', ['add', 32, side]]
                elif side.location == 'storage':
                    return ['sload', ['add', 1, ['sha3_32', side]]]

            return LLLnode.from_list(
                [op, load_bytearray(left), load_bytearray(right)],
                typ='bool',
                pos=getpos(self.expr),
            )

        # Compare other types.
        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            if op not in ('eq', 'ne'):
                raise TypeMismatchException("Invalid type for comparison op", self.expr)
        left_type, right_type = left.typ.typ, right.typ.typ

        # Special Case: comparison of a literal integer. If in valid range allow it to be compared.
        if {left_type, right_type} == {'int128', 'uint256'} and {left.typ.is_literal, right.typ.is_literal} == {True, False}:  # noqa: E501

            comparison_allowed = False
            if left.typ.is_literal and SizeLimits.in_bounds(right_type, left.value):
                comparison_allowed = True
            elif right.typ.is_literal and SizeLimits.in_bounds(left_type, right.value):
                comparison_allowed = True
            op = self._signed_to_unsigned_comparision_op(op)

            if comparison_allowed:
                return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))

        elif {left_type, right_type} == {'uint256', 'uint256'}:
            op = self._signed_to_unsigned_comparision_op(op)
        elif (left_type in ('decimal', 'int128') or right_type in ('decimal', 'int128')) and left_type != right_type:  # noqa: E501
            raise TypeMismatchException(
                'Implicit conversion from {} to {} disallowed, please convert.'.format(
                    left_type,
                    right_type,
                ),
                self.expr,
            )

        if left_type == right_type:
            return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))
        else:
            raise TypeMismatchException(
                "Unsupported types for comparison: %r %r" % (left_type, right_type),
                self.expr,
            )

    def boolean_operations(self):
        # Iterate through values
        for value in self.expr.values:
            # Check for calls at assignment
            if self.context.in_assignment and isinstance(value, ast.Call):
                raise StructureException(
                    "Boolean operations with calls may not be performed on assignment",
                    self.expr,
                )

            # Check for boolean operations with non-boolean inputs
            _expr = Expr.parse_value_expr(value, self.context)
            if not is_base_type(_expr.typ, 'bool'):
                raise TypeMismatchException(
                    "Boolean operations can only be between booleans!",
                    self.expr,
                )

            # TODO: Handle special case of literals and simplify at compile time

        # Check for valid ops
        if isinstance(self.expr.op, ast.And):
            op = 'and'
        elif isinstance(self.expr.op, ast.Or):
            op = 'or'
        else:
            raise Exception("Unsupported bool op: " + self.expr.op)

        # Handle different numbers of inputs
        count = len(self.expr.values)
        if count < 2:
            raise StructureException("Expected at least two arguments for a bool op", self.expr)
        elif count == 2:
            left = Expr.parse_value_expr(self.expr.values[0], self.context)
            right = Expr.parse_value_expr(self.expr.values[1], self.context)
            return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))
        else:
            left = Expr.parse_value_expr(self.expr.values[0], self.context)
            right = Expr.parse_value_expr(self.expr.values[1], self.context)

            p = ['seq', [op, left, right]]
            values = self.expr.values[2:]
            while len(values) > 0:
                value = Expr.parse_value_expr(values[0], self.context)
                p = [op, value, p]
                values = values[1:]

            return LLLnode.from_list(p, typ='bool', pos=getpos(self.expr))

    # Unary operations (only "not" supported)
    def unary_operations(self):
        operand = Expr.parse_value_expr(self.expr.operand, self.context)
        if isinstance(self.expr.op, ast.Not):
            if isinstance(operand.typ, BaseType) and operand.typ.typ == 'bool':
                return LLLnode.from_list(["iszero", operand], typ='bool', pos=getpos(self.expr))
            else:
                raise TypeMismatchException(
                    "Only bool is supported for not operation, %r supplied." % operand.typ,
                    self.expr,
                )
        elif isinstance(self.expr.op, ast.USub):
            if not is_numeric_type(operand.typ):
                raise TypeMismatchException(
                    "Unsupported type for negation: %r" % operand.typ,
                    operand,
                )

            if operand.typ.is_literal and 'int' in operand.typ.typ:
                num = ast.Num(n=0 - operand.value)
                num.source_code = self.expr.source_code
                num.lineno = self.expr.lineno
                num.col_offset = self.expr.col_offset
                return Expr.parse_value_expr(num, self.context)

            return LLLnode.from_list(["sub", 0, operand], typ=operand.typ, pos=getpos(self.expr))
        else:
            raise StructureException("Only the 'not' unary operator is supported")

    def _is_valid_contract_assign(self):
        if self.expr.args and len(self.expr.args) == 1:
            arg_lll = Expr(self.expr.args[0], self.context).lll_node
            if arg_lll.typ == BaseType('address'):
                return True, arg_lll
        return False, None

    # Function calls
    def call(self):
        from vyper.functions import (
            dispatch_table,
        )

        if isinstance(self.expr.func, ast.Name):
            function_name = self.expr.func.id

            if function_name in dispatch_table:
                return dispatch_table[function_name](self.expr, self.context)

            # Struct constructors do not need `self` prefix.
            elif function_name in self.context.structs:
                args = self.expr.args
                if len(args) != 1:
                    raise StructureException(
                        "Struct constructor is called with one argument only",
                        self.expr,
                    )

                arg = args[0]
                if not isinstance(arg, ast.Dict):
                    raise TypeMismatchException(
                        "Struct can only be constructed with a dict",
                        self.expr,
                    )
                return Expr.struct_literals(arg, function_name, self.context)

            # Contract assignment. Bar(<address>).
            elif function_name in self.context.sigs:
                ret, arg_lll = self._is_valid_contract_assign()
                if ret is True:
                    arg_lll.typ = ContractType(function_name)  # Cast to Correct contract type.
                    return arg_lll
                else:
                    raise TypeMismatchException(
                        "ContractType definition expects one address argument.",
                        self.expr,
                    )
            else:
                err_msg = "Not a top-level function: {}".format(function_name)
                if function_name in [x.split('(')[0] for x, _ in self.context.sigs['self'].items()]:
                    err_msg += ". Did you mean self.{}?".format(function_name)
                raise StructureException(err_msg, self.expr)
        elif isinstance(self.expr.func, ast.Attribute) and isinstance(self.expr.func.value, ast.Name) and self.expr.func.value.id == "self":  # noqa: E501
            return self_call.make_call(self.expr, self.context)
        else:
            return external_call.make_external_call(self.expr, self.context)

    def list_literals(self):

        if not len(self.expr.elts):
            raise StructureException("List must have elements", self.expr)

        def get_out_type(lll_node):
            if isinstance(lll_node, ListType):
                return get_out_type(lll_node.subtype)
            return lll_node.typ

        o = []
        previous_type = None
        out_type = None

        for elt in self.expr.elts:
            current_lll_node = Expr(elt, self.context).lll_node
            if not out_type:
                out_type = current_lll_node.typ

            current_type = get_out_type(current_lll_node)
            if len(o) > 1 and previous_type != current_type:
                raise TypeMismatchException("Lists may only contain one type", self.expr)
            else:
                o.append(current_lll_node)
                previous_type = current_type

        return LLLnode.from_list(
            ["multi"] + o,
            typ=ListType(out_type, len(o)),
            pos=getpos(self.expr),
        )

    def dict_fail(self):
        warnings.warn(
            "Anonymous structs have been removed in"
            " favor of named structs, see VIP300",
            DeprecationWarning
        )
        raise InvalidLiteralException("Invalid literal.", self.expr)

    @staticmethod
    def struct_literals(expr, name, context):
        o = {}
        members = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, ast.Name):
                raise TypeMismatchException(
                    "Invalid member variable for struct: %r" % getattr(key, 'id', ''),
                    key,
                )
            check_valid_varname(
                key.id,
                context.custom_units,
                context.structs,
                context.constants,
                "Invalid member variable for struct",
            )
            if key.id in o:
                raise TypeMismatchException("Member variable duplicated: " + key.id, key)
            o[key.id] = Expr(value, context).lll_node
            members[key.id] = o[key.id].typ
        return LLLnode.from_list(
            ["multi"] + [o[key] for key in (list(o.keys()))],
            typ=StructType(members, name, is_literal=True),
            pos=getpos(expr),
        )

    def tuple_literals(self):
        if not len(self.expr.elts):
            raise StructureException("Tuple must have elements", self.expr)
        o = []
        for elt in self.expr.elts:
            o.append(Expr(elt, self.context).lll_node)
        typ = TupleType([x.typ for x in o], is_literal=True)
        return LLLnode.from_list(["multi"] + o, typ=typ, pos=getpos(self.expr))

    # Parse an expression that results in a value
    @classmethod
    def parse_value_expr(cls, expr, context):
        return unwrap_location(cls(expr, context).lll_node)

    # Parse an expression that represents an address in memory or storage
    @classmethod
    def parse_variable_location(cls, expr, context):
        o = cls(expr, context).lll_node
        if not o.location:
            raise ParserException("Looking for a variable location, instead got a value", expr)
        return o
