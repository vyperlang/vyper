import warnings

from vyper import ast as vy_ast
from vyper.exceptions import (
    EvmVersionException,
    InvalidLiteral,
    NonPayableViolation,
    StructureException,
    TypeMismatch,
    VariableDeclarationException,
    ZeroDivisionException,
)
from vyper.opcodes import version_check
from vyper.parser import external_call, self_call
from vyper.parser.keccak256_helper import keccak256_helper
from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import (
    add_variable_offset,
    get_number_as_fraction,
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
    StringType,
    StructType,
    TupleType,
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

# var name: (lllnode, type)
BUILTIN_CONSTANTS = {
    'EMPTY_BYTES32': (0, 'bytes32'),
    'ZERO_ADDRESS': (0, 'address'),
    'MAX_INT128': (SizeLimits.MAXNUM, 'int128'),
    'MIN_INT128': (SizeLimits.MINNUM, 'int128'),
    'MAX_DECIMAL': (SizeLimits.MAXDECIMAL, 'decimal'),
    'MIN_DECIMAL': (SizeLimits.MINDECIMAL, 'decimal'),
    'MAX_UINT256': (SizeLimits.MAX_UINT256, 'uint256'),
}

ENVIRONMENT_VARIABLES = {
    "block",
    "msg",
    "tx",
    "chain",
}


def get_min_val_for_type(typ: str) -> int:
    key = 'MIN_' + typ.upper()
    try:
        min_val, _ = BUILTIN_CONSTANTS[key]
    except KeyError as e:
        raise TypeMismatch(f"Not a signed type: {typ}") from e
    return min_val


class Expr(object):
    # TODO: Once other refactors are made reevaluate all inline imports
    def __init__(self, expr, context):
        self.expr = expr
        self.context = context
        self.expr_table = {
            LLLnode: self.get_expr,
            vy_ast.Int: self.integer,
            vy_ast.Decimal: self.decimal,
            vy_ast.Hex: self.hexstring,
            vy_ast.Str: self.string,
            vy_ast.NameConstant: self.constants,
            vy_ast.Name: self.variables,
            vy_ast.Attribute: self.attribute,
            vy_ast.Subscript: self.subscript,
            vy_ast.BinOp: self.arithmetic,
            vy_ast.Compare: self.compare,
            vy_ast.BoolOp: self.boolean_operations,
            vy_ast.UnaryOp: self.unary_operations,
            vy_ast.Call: self.call,
            vy_ast.List: self.list_literals,
            vy_ast.Tuple: self.tuple_literals,
            vy_ast.Dict: self.dict_fail,
            vy_ast.Bytes: self.bytes,
        }
        expr_type = self.expr.__class__
        if expr_type in self.expr_table:
            self.lll_node = self.expr_table[expr_type]()
        else:
            raise Exception("Unsupported operator.", self.expr)

    def get_expr(self):
        return self.expr

    def integer(self):
        # Literal (mostly likely) becomes int128
        if SizeLimits.in_bounds('int128', self.expr.n) or self.expr.n < 0:
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType('int128', is_literal=True),
                pos=getpos(self.expr),
            )
        # Literal is large enough (mostly likely) becomes uint256.
        else:
            return LLLnode.from_list(
                self.expr.n,
                typ=BaseType('uint256', is_literal=True),
                pos=getpos(self.expr),
            )

    def decimal(self):
        numstring, num, den = get_number_as_fraction(self.expr, self.context)
        # if not SizeLimits.in_bounds('decimal', num // den):
        # if not SizeLimits.MINDECIMAL * den <= num <= SizeLimits.MAXDECIMAL * den:
        if not (SizeLimits.MINNUM * den <= num <= SizeLimits.MAXNUM * den):
            raise InvalidLiteral("Number out of range: " + numstring, self.expr)
        if DECIMAL_DIVISOR % den:
            raise InvalidLiteral(
                "Type 'decimal' has maximum 10 decimal places",
                self.expr
            )
        return LLLnode.from_list(
            num * DECIMAL_DIVISOR // den,
            typ=BaseType('decimal', is_literal=True),
            pos=getpos(self.expr),
        )

    def hexstring(self):
        orignum = self.expr.value
        if len(orignum) == 42:
            if checksum_encode(orignum) != orignum:
                raise InvalidLiteral(
                    "Address checksum mismatch. If you are sure this is the "
                    f"right address, the correct checksummed form is: {checksum_encode(orignum)}",
                    self.expr
                )
            return LLLnode.from_list(
                int(self.expr.value, 16),
                typ=BaseType('address', is_literal=True),
                pos=getpos(self.expr),
            )
        elif len(orignum) == 66:
            return LLLnode.from_list(
                int(self.expr.value, 16),
                typ=BaseType('bytes32', is_literal=True),
                pos=getpos(self.expr),
            )
        else:
            raise InvalidLiteral(
                f"Cannot read 0x value with length {len(orignum)}. Expecting 42 (address "
                "incl 0x) or 66 (bytes32 incl 0x)",
                self.expr
            )

    # String literals
    def string(self):
        bytez, bytez_length = string_to_bytes(self.expr.value)
        typ = StringType(bytez_length, is_literal=True)
        return self._make_bytelike(typ, bytez, bytez_length)

    # Byte literals
    def bytes(self):
        bytez = self.expr.s
        bytez_length = len(self.expr.s)
        typ = ByteArrayType(bytez_length, is_literal=True)
        return self._make_bytelike(typ, bytez, bytez_length)

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
            annotation=f'Create {btype}: {bytez}',
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
            # block None
            raise InvalidLiteral(
                    'None is not allowed in vyper'
                    '(use a default value or built-in `empty()`')
        else:
            raise Exception(f"Unknown name constant: {self.expr.value.value}")

    # Variable names
    def variables(self):

        if self.expr.id == 'self':
            return LLLnode.from_list(['address'], typ='address', pos=getpos(self.expr))
        elif self.expr.id in self.context.vars:
            var = self.context.vars[self.expr.id]
            return LLLnode.from_list(
                var.pos,
                typ=var.typ,
                location=var.location,  # either 'memory' or 'calldata' storage is handled above.
                pos=getpos(self.expr),
                annotation=self.expr.id,
                mutable=var.mutable,
            )

        elif self.expr.id in BUILTIN_CONSTANTS:
            obj, typ = BUILTIN_CONSTANTS[self.expr.id]
            return LLLnode.from_list(
                [obj],
                typ=BaseType(typ, is_literal=True),
                pos=getpos(self.expr))
        else:
            raise VariableDeclarationException(f"Undeclared variable: {self.expr.id}", self.expr)

    # x.y or x[5]
    def attribute(self):
        # x.balance: balance of address x
        if self.expr.attr == 'balance':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatch(
                    "Type mismatch: balance keyword expects an address as input",
                    self.expr
                )
            if (
                isinstance(self.expr.value, vy_ast.Name) and
                self.expr.value.id == "self" and
                version_check(begin="istanbul")
            ):
                seq = ['selfbalance']
            else:
                seq = ['balance', addr]
            return LLLnode.from_list(
                seq,
                typ=BaseType('uint256'),
                location=None,
                pos=getpos(self.expr),
            )
        # x.codesize: codesize of address x
        elif self.expr.attr == 'codesize' or self.expr.attr == 'is_contract':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatch(
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
        # x.codehash: keccak of address x
        elif self.expr.attr == 'codehash':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatch(
                    "codehash keyword expects an address as input",
                    self.expr,
                )
            if not version_check(begin="constantinople"):
                raise EvmVersionException(
                    "address.codehash is unavailable prior to constantinople ruleset",
                    self.expr
                )
            return LLLnode.from_list(
                ['extcodehash', addr],
                typ=BaseType('bytes32'),
                location=None,
                pos=getpos(self.expr)
            )
        # self.x: global attribute
        elif isinstance(self.expr.value, vy_ast.Name) and self.expr.value.id == "self":
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
        elif (
            isinstance(self.expr.value, vy_ast.Name) and
            self.expr.value.id in ENVIRONMENT_VARIABLES
        ):
            key = self.expr.value.id + "." + self.expr.attr
            if key == "msg.sender":
                if self.context.is_private:
                    raise StructureException(
                        "msg.sender not allowed in private functions.", self.expr
                    )
                return LLLnode.from_list(['caller'], typ='address', pos=getpos(self.expr))
            elif key == "msg.value":
                if not self.context.is_payable:
                    raise NonPayableViolation(
                        "Cannot use msg.value in a non-payable function", self.expr,
                    )
                return LLLnode.from_list(
                    ['callvalue'],
                    typ=BaseType('uint256'),
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
                    typ=BaseType('uint256'),
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
            elif key == "chain.id":
                if not version_check(begin="istanbul"):
                    raise EvmVersionException(
                        "chain.id is unavailable prior to istanbul ruleset",
                        self.expr
                    )
                return LLLnode.from_list(['chainid'], typ='uint256', pos=getpos(self.expr))
            else:
                raise StructureException("Unsupported keyword: " + key, self.expr)
        # Other variables
        else:
            sub = Expr.parse_variable_location(self.expr.value, self.context)
            # contract type
            if isinstance(sub.typ, ContractType):
                return sub
            if not isinstance(sub.typ, StructType):
                raise TypeMismatch(
                    "Type mismatch: member variable access not expected",
                    self.expr.value,
                )
            attrs = list(sub.typ.members.keys())
            if self.expr.attr not in attrs:
                raise TypeMismatch(
                    f"Member {self.expr.attr} not found. Only the following available: "
                    f"{' '.join(attrs)}",
                    self.expr,
                )
            return add_variable_offset(sub, self.expr.attr, pos=getpos(self.expr))

    def subscript(self):
        sub = Expr.parse_variable_location(self.expr.value, self.context)
        if isinstance(sub.typ, (MappingType, ListType)):
            if not isinstance(self.expr.slice, vy_ast.Index):
                raise StructureException(
                    "Array access must access a single element, not a slice",
                    self.expr,
                )
            index = Expr.parse_value_expr(self.expr.slice.value, self.context)
        elif isinstance(sub.typ, TupleType):
            if not isinstance(self.expr.slice.value, vy_ast.Int) or self.expr.slice.value.n < 0 or self.expr.slice.value.n >= len(sub.typ.members):  # noqa: E501
                raise TypeMismatch("Tuple index invalid", self.expr.slice.value)
            index = self.expr.slice.value.n
        else:
            raise TypeMismatch("Bad subscript attempt", self.expr.value)
        o = add_variable_offset(sub, index, pos=getpos(self.expr))
        o.mutable = sub.mutable
        return o

    def arithmetic(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            raise TypeMismatch(
                f"Unsupported types for arithmetic op: {left.typ} {right.typ}",
                self.expr,
            )

        arithmetic_pair = {left.typ.typ, right.typ.typ}
        pos = getpos(self.expr)

        # Special case with uint256 were int literal may be casted.
        if arithmetic_pair == {'uint256', 'int128'}:
            # Check right side literal.
            if right.typ.is_literal and SizeLimits.in_bounds('uint256', right.value):
                right = LLLnode.from_list(
                    right.value,
                    typ=BaseType('uint256', None, is_literal=True),
                    pos=pos,
                )

            # Check left side literal.
            elif left.typ.is_literal and SizeLimits.in_bounds('uint256', left.value):
                left = LLLnode.from_list(
                    left.value,
                    typ=BaseType('uint256', None, is_literal=True),
                    pos=pos,
                )

        if left.typ.typ == "decimal" and isinstance(self.expr.op, vy_ast.Pow):
            raise TypeMismatch(
                "Cannot perform exponentiation on decimal values.",
                self.expr,
            )

        # Only allow explicit conversions to occur.
        if left.typ.typ != right.typ.typ:
            raise TypeMismatch(
                f"Cannot implicitly convert {left.typ.typ} to {right.typ.typ}.",
                self.expr,
            )

        ltyp, rtyp = left.typ.typ, right.typ.typ
        if isinstance(self.expr.op, (vy_ast.Add, vy_ast.Sub)):
            new_typ = BaseType(ltyp)
            op = 'add' if isinstance(self.expr.op, vy_ast.Add) else 'sub'

            if ltyp == 'uint256' and isinstance(self.expr.op, vy_ast.Add):
                # safeadd
                arith = ['seq',
                         ['assert', ['ge', ['add', 'l', 'r'], 'l']],
                         ['add', 'l', 'r']]

            elif ltyp == 'uint256' and isinstance(self.expr.op, vy_ast.Sub):
                # safesub
                arith = ['seq',
                         ['assert', ['ge', 'l', 'r']],
                         ['sub', 'l', 'r']]

            elif ltyp == rtyp:
                arith = [op, 'l', 'r']

            else:
                raise Exception(f"Unsupported Operation '{op}({ltyp}, {rtyp})'")

        elif isinstance(self.expr.op, vy_ast.Mult):
            new_typ = BaseType(ltyp)
            if ltyp == rtyp == 'uint256':
                arith = ['with', 'ans', ['mul', 'l', 'r'],
                         ['seq',
                             ['assert',
                                 ['or',
                                     ['eq', ['div', 'ans', 'l'], 'r'],
                                     ['iszero', 'l']]],
                             'ans']]

            elif ltyp == rtyp == 'int128':
                # TODO should this be 'smul' (note edge cases in YP for smul)
                arith = ['mul', 'l', 'r']

            elif ltyp == rtyp == 'decimal':
                # TODO should this be smul
                arith = ['with', 'ans', ['mul', 'l', 'r'],
                         ['seq',
                             ['assert',
                                 ['or',
                                     ['eq', ['sdiv', 'ans', 'l'], 'r'],
                                     ['iszero', 'l']]],
                             ['sdiv', 'ans', DECIMAL_DIVISOR]]]
            else:
                raise Exception(f"Unsupported Operation 'mul({ltyp}, {rtyp})'")

        elif isinstance(self.expr.op, vy_ast.Div):
            if right.typ.is_literal and right.value == 0:
                raise ZeroDivisionException("Cannot divide by 0.", self.expr)

            new_typ = BaseType(ltyp)
            if ltyp == rtyp == 'uint256':
                arith = ['div', 'l', ['clamp_nonzero', 'r']]

            elif ltyp == rtyp == 'int128':
                arith = ['sdiv', 'l', ['clamp_nonzero', 'r']]

            elif ltyp == rtyp == 'decimal':
                arith = ['sdiv',
                         # TODO check overflow cases, also should it be smul
                         ['mul', 'l', DECIMAL_DIVISOR],
                         ['clamp_nonzero', 'r']]

            else:
                raise Exception(f"Unsupported Operation 'div({ltyp}, {rtyp})'")

        elif isinstance(self.expr.op, vy_ast.Mod):
            if right.typ.is_literal and right.value == 0:
                raise ZeroDivisionException("Cannot calculate modulus of 0.", self.expr)

            new_typ = BaseType(ltyp)

            if ltyp == rtyp == 'uint256':
                arith = ['mod', 'l', ['clamp_nonzero', 'r']]
            elif ltyp == rtyp:
                # TODO should this be regular mod
                arith = ['smod', 'l', ['clamp_nonzero', 'r']]

            else:
                raise Exception(f"Unsupported Operation 'mod({ltyp}, {rtyp})'")
        elif isinstance(self.expr.op, vy_ast.Pow):
            if ltyp != 'int128' and ltyp != 'uint256' and isinstance(self.expr.right, vy_ast.Name):
                raise TypeMismatch(
                    "Cannot use dynamic values as exponents, for unit base types",
                    self.expr,
                )
            new_typ = BaseType(ltyp)

            if ltyp == rtyp == 'uint256':
                arith = ['seq',
                         ['assert',
                             ['or',
                                 # r == 1 | iszero(r)
                                 # could be simplified to ~(r & 1)
                                 ['or', ['eq', 'r', 1], ['iszero', 'r']],
                                 ['lt', 'l', ['exp', 'l', 'r']]]],
                         ['exp', 'l', 'r']]
            elif ltyp == rtyp == 'int128':
                arith = ['exp', 'l', 'r']

            else:
                raise TypeMismatch('Only whole number exponents are supported', self.expr)
        else:
            raise StructureException(f"Unsupported binary operator: {self.expr.op}", self.expr)

        p = ['seq']

        if new_typ.typ == 'int128':
            p.append([
                'clamp',
                ['mload', MemoryPositions.MINNUM],
                arith,
                ['mload', MemoryPositions.MAXNUM],
            ])
        elif new_typ.typ == 'decimal':
            p.append([
                'clamp',
                ['mload', MemoryPositions.MINDECIMAL],
                arith,
                ['mload', MemoryPositions.MAXDECIMAL],
            ])
        elif new_typ.typ == 'uint256':
            p.append(arith)
        else:
            raise Exception(f"{arith} {new_typ}")

        p = ['with', 'l', left, ['with', 'r', right, p]]
        return LLLnode.from_list(p, typ=new_typ, pos=pos)

    def build_in_comparator(self):
        left = Expr(self.expr.left, self.context).lll_node
        right = Expr(self.expr.right, self.context).lll_node

        if left.typ != right.typ.subtype:
            raise TypeMismatch(
                f"{left.typ} cannot be in a list of {right.typ.subtype}",
                self.expr,
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
        right = Expr.parse_value_expr(self.expr.right, self.context)

        if right.value is None:
            raise InvalidLiteral(
                'Comparison to None is not allowed, compare against a default value.',
                self.expr,
            )

        if isinstance(left.typ, ByteArrayLike) and isinstance(right.typ, ByteArrayLike):
            # TODO: Can this if branch be removed ^
            pass

        elif isinstance(self.expr.op, vy_ast.In) and isinstance(right.typ, ListType):
            if left.typ != right.typ.subtype:
                raise TypeMismatch(
                    "Can't use IN comparison with different types!",
                    self.expr,
                )
            return self.build_in_comparator()

        if isinstance(self.expr.op, vy_ast.Gt):
            op = 'sgt'
        elif isinstance(self.expr.op, vy_ast.GtE):
            op = 'sge'
        elif isinstance(self.expr.op, vy_ast.LtE):
            op = 'sle'
        elif isinstance(self.expr.op, vy_ast.Lt):
            op = 'slt'
        elif isinstance(self.expr.op, vy_ast.Eq):
            op = 'eq'
        elif isinstance(self.expr.op, vy_ast.NotEq):
            op = 'ne'
        else:
            raise Exception("Unsupported comparison operator")

        # Compare (limited to 32) byte arrays.
        if isinstance(left.typ, ByteArrayLike) and isinstance(right.typ, ByteArrayLike):
            left = Expr(self.expr.left, self.context).lll_node
            right = Expr(self.expr.right, self.context).lll_node

            length_mismatch = (left.typ.maxlen != right.typ.maxlen)
            left_over_32 = left.typ.maxlen > 32
            right_over_32 = right.typ.maxlen > 32
            if length_mismatch or left_over_32 or right_over_32:
                left_keccak = keccak256_helper(self.expr, [left], None, self.context)
                right_keccak = keccak256_helper(self.expr, [right], None, self.context)

                if op == 'eq' or op == 'ne':
                    return LLLnode.from_list(
                        [op, left_keccak, right_keccak],
                        typ='bool',
                        pos=getpos(self.expr),
                    )

                else:
                    raise StructureException(
                        "Can only compare strings/bytes of length shorter",
                        " than 32 bytes other than equality comparisons",
                        self.expr,
                    )

            else:
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
                raise TypeMismatch("Invalid type for comparison op", self.expr)
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
            raise TypeMismatch(
                f'Implicit conversion from {left_type} to {right_type} disallowed, please convert.',
                self.expr,
            )

        if left_type == right_type:
            return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))
        else:
            raise TypeMismatch(
                f"Unsupported types for comparison: {left_type} {right_type}",
                self.expr,
            )

    def boolean_operations(self):
        # Iterate through values
        for value in self.expr.values:
            # Check for calls at assignment
            if self.context.in_assignment and isinstance(value, vy_ast.Call):
                raise StructureException(
                    "Boolean operations with calls may not be performed on assignment",
                    self.expr,
                )

            # Check for boolean operations with non-boolean inputs
            _expr = Expr.parse_value_expr(value, self.context)
            if not is_base_type(_expr.typ, 'bool'):
                raise TypeMismatch(
                    "Boolean operations can only be between booleans!",
                    self.expr,
                )

            # TODO: Handle special case of literals and simplify at compile time

        # Check for valid ops
        if isinstance(self.expr.op, vy_ast.And):
            op = 'and'
        elif isinstance(self.expr.op, vy_ast.Or):
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
        if isinstance(self.expr.op, vy_ast.Not):
            if isinstance(operand.typ, BaseType) and operand.typ.typ == 'bool':
                return LLLnode.from_list(["iszero", operand], typ='bool', pos=getpos(self.expr))
            else:
                raise TypeMismatch(
                    f"Only bool is supported for not operation, {operand.typ} supplied.",
                    self.expr,
                )
        elif isinstance(self.expr.op, vy_ast.USub):
            if not is_numeric_type(operand.typ):
                raise TypeMismatch(
                    f"Unsupported type for negation: {operand.typ}",
                    self.expr,
                )

            # Clamp on minimum integer value as we cannot negate that value
            # (all other integer values are fine)
            min_int_val = get_min_val_for_type(operand.typ.typ)
            return LLLnode.from_list(
                    ["sub", 0, ["clampgt", operand, min_int_val]],
                    typ=operand.typ,
                    pos=getpos(self.expr)
                )
        else:
            raise StructureException("Only the 'not' or 'neg' unary operators are supported")

    def _is_valid_contract_assign(self):
        if self.expr.args and len(self.expr.args) == 1:
            arg_lll = Expr(self.expr.args[0], self.context).lll_node
            if arg_lll.typ == BaseType('address'):
                return True, arg_lll
        return False, None

    # Function calls
    def call(self):
        from vyper.functions import (
            DISPATCH_TABLE,
        )

        if isinstance(self.expr.func, vy_ast.Name):
            function_name = self.expr.func.id

            if function_name in DISPATCH_TABLE:
                return DISPATCH_TABLE[function_name].build_LLL(self.expr, self.context)

            # Struct constructors do not need `self` prefix.
            elif function_name in self.context.structs:
                args = self.expr.args
                if len(args) != 1:
                    raise StructureException(
                        "Struct constructor is called with one argument only",
                        self.expr,
                    )

                arg = args[0]
                if not isinstance(arg, vy_ast.Dict):
                    raise TypeMismatch(
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
                    raise TypeMismatch(
                        "ContractType definition expects one address argument.",
                        self.expr,
                    )
            else:
                err_msg = f"Not a top-level function: {function_name}"
                if function_name in [x.split('(')[0] for x, _ in self.context.sigs['self'].items()]:
                    err_msg += f". Did you mean self.{function_name}?"
                raise StructureException(err_msg, self.expr)
        elif isinstance(self.expr.func, vy_ast.Attribute) and isinstance(self.expr.func.value, vy_ast.Name) and self.expr.func.value.id == "self":  # noqa: E501
            return self_call.make_call(self.expr, self.context)
        else:
            return external_call.make_external_call(self.expr, self.context)

    def list_literals(self):

        if not len(self.expr.elements):
            raise StructureException("List must have elements", self.expr)

        def get_out_type(lll_node):
            if isinstance(lll_node, ListType):
                return get_out_type(lll_node.subtype)
            return lll_node.typ

        o = []
        previous_type = None
        out_type = None

        for elt in self.expr.elements:
            current_lll_node = Expr(elt, self.context).lll_node
            if not out_type:
                out_type = current_lll_node.typ

            current_type = get_out_type(current_lll_node)
            if len(o) > 0 and previous_type != current_type:
                raise TypeMismatch("Lists may only contain one type", self.expr)
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
        raise InvalidLiteral("Invalid literal.", self.expr)

    @staticmethod
    def struct_literals(expr, name, context):
        member_subs = {}
        member_typs = {}
        for key, value in zip(expr.keys, expr.values):
            if not isinstance(key, vy_ast.Name):
                raise TypeMismatch(
                    f"Invalid member variable for struct: {getattr(key, 'id', '')}",
                    key,
                )
            check_valid_varname(
                key.id,
                context.structs,
                context.constants,
                "Invalid member variable for struct",
            )
            if key.id in member_subs:
                raise TypeMismatch("Member variable duplicated: " + key.id, key)
            sub = Expr(value, context).lll_node
            member_subs[key.id] = sub
            member_typs[key.id] = sub.typ
        return LLLnode.from_list(
            ["multi"] + [member_subs[key] for key in member_subs.keys()],
            typ=StructType(member_typs, name, is_literal=True),
            pos=getpos(expr),
        )

    def tuple_literals(self):
        if not len(self.expr.elements):
            raise StructureException("Tuple must have elements", self.expr)
        o = []
        for elt in self.expr.elements:
            o.append(Expr(elt, self.context).lll_node)
        typ = TupleType([x.typ for x in o], is_literal=True)
        return LLLnode.from_list(["multi"] + o, typ=typ, pos=getpos(self.expr))

    # Parse an expression that results in a value
    @classmethod
    def parse_value_expr(cls, expr, context):
        return unwrap_location(cls(expr, context).lll_node)

    # Parse an expression that represents an address in memory/calldata or storage.
    @classmethod
    def parse_variable_location(cls, expr, context):
        o = cls(expr, context).lll_node
        if not o.location:
            raise StructureException("Looking for a variable location, instead got a value", expr)
        return o
