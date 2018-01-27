import ast

from viper.exceptions import (
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
    InvalidLiteralException,
    NonPayableViolationException,
)
from .parser_utils import LLLnode
from .parser_utils import (
    getpos,
    unwrap_location,
    get_original_if_0x_prefixed,
    get_number_as_fraction,
    add_variable_offset,
)
from viper.utils import (
    MemoryPositions,
    SizeLimits,
    bytes_to_int,
    string_to_bytes,
    DECIMAL_DIVISOR,
    checksum_encode,
    is_varname_valid,
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
)
from viper.types import (
    are_units_compatible,
    is_numeric_type,
    combine_units
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
            ast.Dict: self.struct_literals,
            ast.Tuple: self.tuple_literals,
        }
        expr_type = self.expr.__class__
        if expr_type in self.expr_table:
            self.lll_node = self.expr_table[expr_type]()
        else:
            raise Exception("Unsupported operator: %r" % ast.dump(self.expr))

    def get_expr(self):
        return self.expr

    def number(self):
        orignum = get_original_if_0x_prefixed(self.expr, self.context)
        if orignum is None and isinstance(self.expr.n, int):
            if not (SizeLimits.MINNUM <= self.expr.n <= SizeLimits.MAXNUM):
                raise InvalidLiteralException("Number out of range: " + str(self.expr.n), self.expr)
            return LLLnode.from_list(self.expr.n, typ=BaseType('num', None), pos=getpos(self.expr))
        elif isinstance(self.expr.n, float):
            numstring, num, den = get_number_as_fraction(self.expr, self.context)
            if not (SizeLimits.MINNUM * den < num < SizeLimits.MAXNUM * den):
                raise InvalidLiteralException("Number out of range: " + numstring, self.expr)
            if DECIMAL_DIVISOR % den:
                raise InvalidLiteralException("Too many decimal places: " + numstring, self.expr)
            return LLLnode.from_list(num * DECIMAL_DIVISOR // den, typ=BaseType('decimal', None), pos=getpos(self.expr))
        elif len(orignum) == 42:
            if checksum_encode(orignum) != orignum:
                raise InvalidLiteralException("Address checksum mismatch. If you are sure this is the "
                                              "right address, the correct checksummed form is: " +
                                              checksum_encode(orignum), self.expr)
            return LLLnode.from_list(self.expr.n, typ=BaseType('address'), pos=getpos(self.expr))
        elif len(orignum) == 66:
            return LLLnode.from_list(self.expr.n, typ=BaseType('bytes32'), pos=getpos(self.expr))
        else:
            raise InvalidLiteralException("Cannot read 0x value with length %d. Expecting 42 (address incl 0x) or 66 (bytes32 incl 0x)"
                                          % len(orignum), self.expr)

    # Byte array literals
    def string(self):
        bytez, bytez_length = string_to_bytes(self.expr.s)
        placeholder = self.context.new_placeholder(ByteArrayType(bytez_length))
        seq = []
        seq.append(['mstore', placeholder, bytez_length])
        for i in range(0, len(bytez), 32):
            seq.append(['mstore', ['add', placeholder, i + 32], bytes_to_int((bytez + b'\x00' * 31)[i: i + 32])])
        return LLLnode.from_list(['seq'] + seq + [placeholder], typ=ByteArrayType(bytez_length), location='memory', pos=getpos(self.expr))

    # True, False, None constants
    def constants(self):
        if self.expr.value is True:
            return LLLnode.from_list(1, typ='bool', pos=getpos(self.expr))
        elif self.expr.value is False:
            return LLLnode.from_list(0, typ='bool', pos=getpos(self.expr))
        elif self.expr.value is None:
            return LLLnode.from_list(None, typ=NullType(), pos=getpos(self.expr))
        else:
            raise Exception("Unknown name constant: %r" % self.expr.value.value)

    # Variable names
    def variables(self):
        if self.expr.id == 'self':
            return LLLnode.from_list(['address'], typ='address', pos=getpos(self.expr))
        if self.expr.id == 'true':
            return LLLnode.from_list(1, typ='bool', pos=getpos(self.expr))
        if self.expr.id == 'false':
            return LLLnode.from_list(0, typ='bool', pos=getpos(self.expr))
        if self.expr.id == 'null':
            return LLLnode.from_list(None, typ=NullType(), pos=getpos(self.expr))
        if self.expr.id in self.context.vars:
            var = self.context.vars[self.expr.id]
            return LLLnode.from_list(var.pos, typ=var.typ, location='memory', pos=getpos(self.expr), annotation=self.expr.id, mutable=var.mutable)
        else:
            raise VariableDeclarationException("Undeclared variable: " + self.expr.id, self.expr)

    # x.y or x[5]
    def attribute(self):
        # x.balance: balance of address x
        if self.expr.attr == 'balance':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException("Type mismatch: balance keyword expects an address as input", self.expr)
            return LLLnode.from_list(['balance', addr], typ=BaseType('num', {'wei': 1}), location=None, pos=getpos(self.expr))
        # x.codesize: codesize of address x
        elif self.expr.attr == 'codesize' or self.expr.attr == 'is_contract':
            addr = Expr.parse_value_expr(self.expr.value, self.context)
            if not is_base_type(addr.typ, 'address'):
                raise TypeMismatchException("Type mismatch: codesize keyword expects an address as input", self.expr)
            if self.expr.attr == 'codesize':
                output_type = 'num'
            else:
                output_type = 'bool'
            return LLLnode.from_list(['extcodesize', addr], typ=BaseType(output_type), location=None, pos=getpos(self.expr))
        # self.x: global attribute
        elif isinstance(self.expr.value, ast.Name) and self.expr.value.id == "self":
            if self.expr.attr not in self.context.globals:
                raise VariableDeclarationException("Persistent variable undeclared: " + self.expr.attr, self.expr)
            var = self.context.globals[self.expr.attr]
            return LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(self.expr), annotation='self.' + self.expr.attr)
        # Reserved keywords
        elif isinstance(self.expr.value, ast.Name) and self.expr.value.id in ("msg", "block", "tx"):
            key = self.expr.value.id + "." + self.expr.attr
            if key == "msg.sender":
                return LLLnode.from_list(['caller'], typ='address', pos=getpos(self.expr))
            elif key == "msg.value":
                if not self.context.is_payable:
                    raise NonPayableViolationException("Cannot use msg.value in a non-payable function", self.expr)
                return LLLnode.from_list(['callvalue'], typ=BaseType('num', {'wei': 1}), pos=getpos(self.expr))
            elif key == "msg.gas":
                return LLLnode.from_list(['gas'], typ='num', pos=getpos(self.expr))
            elif key == "block.difficulty":
                return LLLnode.from_list(['difficulty'], typ='num', pos=getpos(self.expr))
            elif key == "block.timestamp":
                return LLLnode.from_list(['timestamp'], typ=BaseType('num', {'sec': 1}, True), pos=getpos(self.expr))
            elif key == "block.coinbase":
                return LLLnode.from_list(['coinbase'], typ='address', pos=getpos(self.expr))
            elif key == "block.number":
                return LLLnode.from_list(['number'], typ='num', pos=getpos(self.expr))
            elif key == "block.prevhash":
                return LLLnode.from_list(['blockhash', ['sub', 'number', 1]], typ='bytes32', pos=getpos(self.expr))
            elif key == "tx.origin":
                return LLLnode.from_list(['origin'], typ='address', pos=getpos(self.expr))
            else:
                raise Exception("Unsupported keyword: " + key)
        # Other variables
        else:
            sub = Expr.parse_variable_location(self.expr.value, self.context)
            if not isinstance(sub.typ, StructType):
                raise TypeMismatchException("Type mismatch: member variable access not expected", self.expr.value)
            attrs = sorted(sub.typ.members.keys())
            if self.expr.attr not in attrs:
                raise TypeMismatchException("Member %s not found. Only the following available: %s" % (self.expr.attr, " ".join(attrs)), self.expr)
            return add_variable_offset(sub, self.expr.attr)

    def subscript(self):
        sub = Expr.parse_variable_location(self.expr.value, self.context)
        if isinstance(sub.typ, (MappingType, ListType)):
            if 'value' not in vars(self.expr.slice):
                raise StructureException("Array access must access a single element, not a slice", self.expr)
            index = Expr.parse_value_expr(self.expr.slice.value, self.context)
        elif isinstance(sub.typ, TupleType):
            if not isinstance(self.expr.slice.value, ast.Num) or self.expr.slice.value.n < 0 or self.expr.slice.value.n >= len(sub.typ.members):
                raise TypeMismatchException("Tuple index invalid", self.expr.slice.value)
            index = self.expr.slice.value.n
        else:
            raise TypeMismatchException("Bad subscript attempt", self.expr.value)
        o = add_variable_offset(sub, index)
        o.mutable = sub.mutable
        return o

    def arithmetic(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.right, self.context)
        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            raise TypeMismatchException("Unsupported types for arithmetic op: %r %r" % (left.typ, right.typ), self.expr)
        ltyp, rtyp = left.typ.typ, right.typ.typ
        if isinstance(self.expr.op, (ast.Add, ast.Sub)):
            if left.typ.unit != right.typ.unit and left.typ.unit is not None and right.typ.unit is not None:
                raise TypeMismatchException("Unit mismatch: %r %r" % (left.typ.unit, right.typ.unit), self.expr)
            if left.typ.positional and right.typ.positional and isinstance(self.expr.op, ast.Add):
                raise TypeMismatchException("Cannot add two positional units!", self.expr)
            new_unit = left.typ.unit or right.typ.unit
            new_positional = left.typ.positional ^ right.typ.positional  # xor, as subtracting two positionals gives a delta
            op = 'add' if isinstance(self.expr.op, ast.Add) else 'sub'
            if ltyp == rtyp:
                o = LLLnode.from_list([op, left, right], typ=BaseType(ltyp, new_unit, new_positional), pos=getpos(self.expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right],
                                      typ=BaseType('decimal', new_unit, new_positional), pos=getpos(self.expr))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit, new_positional), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation '%r(%r, %r)'" % (op, ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Mult):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot multiply positional values!", self.expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit)
            if ltyp == rtyp == 'num':
                o = LLLnode.from_list(['mul', left, right], typ=BaseType('num', new_unit), pos=getpos(self.expr))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                ['sdiv', 'ans', DECIMAL_DIVISOR]]]]], typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            elif (ltyp == 'num' and rtyp == 'decimal') or (ltyp == 'decimal' and rtyp == 'num'):
                o = LLLnode.from_list(['with', 'r', right, ['with', 'l', left,
                                        ['with', 'ans', ['mul', 'l', 'r'],
                                            ['seq',
                                                ['assert', ['or', ['eq', ['sdiv', 'ans', 'l'], 'r'], ['not', 'l']]],
                                                'ans']]]], typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation 'mul(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Div):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot divide positional values!", self.expr)
            new_unit = combine_units(left.typ.unit, right.typ.unit, div=True)
            if rtyp == 'num':
                o = LLLnode.from_list(['sdiv', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit), pos=getpos(self.expr))
            elif ltyp == rtyp == 'decimal':
                o = LLLnode.from_list(['with', 'l', left, ['with', 'r', ['clamp_nonzero', right],
                                            ['sdiv', ['mul', 'l', DECIMAL_DIVISOR], 'r']]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['sdiv', ['mul', left, DECIMAL_DIVISOR ** 2], ['clamp_nonzero', right]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation 'div(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Mod):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot use positional values as modulus arguments!", self.expr)
            if left.typ.unit != right.typ.unit and left.typ.unit is not None and right.typ.unit is not None:
                raise TypeMismatchException("Modulus arguments must have same unit", self.expr)
            new_unit = left.typ.unit or right.typ.unit
            if ltyp == rtyp:
                o = LLLnode.from_list(['smod', left, ['clamp_nonzero', right]], typ=BaseType(ltyp, new_unit), pos=getpos(self.expr))
            elif ltyp == 'decimal' and rtyp == 'num':
                o = LLLnode.from_list(['smod', left, ['mul', ['clamp_nonzero', right], DECIMAL_DIVISOR]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            elif ltyp == 'num' and rtyp == 'decimal':
                o = LLLnode.from_list(['smod', ['mul', left, DECIMAL_DIVISOR], ['clamp_nonzero', right]],
                                      typ=BaseType('decimal', new_unit), pos=getpos(self.expr))
            else:
                raise Exception("Unsupported Operation 'mod(%r, %r)'" % (ltyp, rtyp))
        elif isinstance(self.expr.op, ast.Pow):
            if left.typ.positional or right.typ.positional:
                raise TypeMismatchException("Cannot use positional values as exponential arguments!", self.expr)
            if right.typ.unit:
                raise TypeMismatchException("Cannot use unit values as exponents", self.expr)
            if ltyp != 'num' and isinstance(self.expr.right, ast.Name):
                raise TypeMismatchException("Cannot use dynamic values as exponents, for unit base types", self.expr)
            if ltyp == rtyp == 'num':
                new_unit = left.typ.unit
                if left.typ.unit and not isinstance(self.expr.right, ast.Name):
                    new_unit = {left.typ.unit.copy().popitem()[0]: self.expr.right.n}
                o = LLLnode.from_list(['exp', left, right], typ=BaseType('num', new_unit), pos=getpos(self.expr))
            else:
                raise TypeMismatchException('Only whole number exponents are supported', self.expr)
        else:
            raise Exception("Unsupported binop: %r" % self.expr.op)
        if o.typ.typ == 'num':
            return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINNUM], o, ['mload', MemoryPositions.MAXNUM]], typ=o.typ, pos=getpos(self.expr))
        elif o.typ.typ == 'decimal':
            return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINDECIMAL], o, ['mload', MemoryPositions.MAXDECIMAL]], typ=o.typ, pos=getpos(self.expr))
        else:
            raise Exception("%r %r" % (o, o.typ))

    def build_in_comparator(self):
        from viper.parser.parser import make_setter
        left = Expr(self.expr.left, self.context).lll_node
        right = Expr(self.expr.comparators[0], self.context).lll_node

        if left.typ.typ != right.typ.subtype.typ:
            raise TypeMismatchException("%s cannot be in a list of %s" % (left.typ.typ, right.typ.subtype.typ))
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
            setter = make_setter(tmp_list, right, 'memory')
            load_i_from_list = ['mload', ['add', tmp_list, ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]]]
        elif right.location == "storage":
            load_i_from_list = ['sload', ['add', ['sha3_32', right], ['mload', MemoryPositions.FREE_LOOP_INDEX]]]
        else:
            load_i_from_list = ['mload', ['add', right, ['mul', 32, ['mload', MemoryPositions.FREE_LOOP_INDEX]]]]

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
            ['with', '_result', result_placeholder,
                ['repeat', MemoryPositions.FREE_LOOP_INDEX, 0, right.typ.count, break_loop_condition]],
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

    def compare(self):
        left = Expr.parse_value_expr(self.expr.left, self.context)
        right = Expr.parse_value_expr(self.expr.comparators[0], self.context)
        if isinstance(self.expr.ops[0], ast.In) and \
           isinstance(right.typ, ListType):
            if not are_units_compatible(left.typ, right.typ.subtype) and not are_units_compatible(right.typ.subtype, left.typ):
                raise TypeMismatchException("Can't use IN comparison with different types!", self.expr)
            return self.build_in_comparator()
        else:
            if not are_units_compatible(left.typ, right.typ) and not are_units_compatible(right.typ, left.typ):
                raise TypeMismatchException("Can't compare values with different units!", self.expr)
        if len(self.expr.ops) != 1:
            raise StructureException("Cannot have a comparison with more than two elements", self.expr)
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
        if not is_numeric_type(left.typ) or not is_numeric_type(right.typ):
            if op not in ('eq', 'ne'):
                raise TypeMismatchException("Invalid type for comparison op", self.expr)
        ltyp, rtyp = left.typ.typ, right.typ.typ
        if ltyp == rtyp:
            return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))
        elif ltyp == 'decimal' and rtyp == 'num':
            return LLLnode.from_list([op, left, ['mul', right, DECIMAL_DIVISOR]], typ='bool', pos=getpos(self.expr))
        elif ltyp == 'num' and rtyp == 'decimal':
            return LLLnode.from_list([op, ['mul', left, DECIMAL_DIVISOR], right], typ='bool', pos=getpos(self.expr))
        else:
            raise TypeMismatchException("Unsupported types for comparison: %r %r" % (ltyp, rtyp), self.expr)

    def boolean_operations(self):
        if len(self.expr.values) != 2:
            raise StructureException("Expected two arguments for a bool op", self.expr)
        left = Expr.parse_value_expr(self.expr.values[0], self.context)
        right = Expr.parse_value_expr(self.expr.values[1], self.context)
        if not is_base_type(left.typ, 'bool') or not is_base_type(right.typ, 'bool'):
            raise TypeMismatchException("Boolean operations can only be between booleans!", self.expr)
        if isinstance(self.expr.op, ast.And):
            op = 'and'
        elif isinstance(self.expr.op, ast.Or):
            op = 'or'
        else:
            raise Exception("Unsupported bool op: " + self.expr.op)
        return LLLnode.from_list([op, left, right], typ='bool', pos=getpos(self.expr))

    # Unary operations (only "not" supported)
    def unary_operations(self):
        operand = Expr.parse_value_expr(self.expr.operand, self.context)
        if isinstance(self.expr.op, ast.Not):
            # Note that in the case of bool, num, address, decimal, num256 AND bytes32,
            # a zero entry represents false, all others represent true
            return LLLnode.from_list(["iszero", operand], typ='bool', pos=getpos(self.expr))
        elif isinstance(self.expr.op, ast.USub):
            if not is_numeric_type(operand.typ):
                raise TypeMismatchException("Unsupported type for negation: %r" % operand.typ, operand)
            return LLLnode.from_list(["sub", 0, operand], typ=operand.typ, pos=getpos(self.expr))
        else:
            raise StructureException("Only the 'not' unary operator is supported")

    # Function calls
    def call(self):
        from .parser import (
            external_contract_call_expr,
            pack_arguments,
        )
        from viper.functions import (
            dispatch_table,
        )
        if isinstance(self.expr.func, ast.Name):
            function_name = self.expr.func.id
            if function_name in dispatch_table:
                return dispatch_table[function_name](self.expr, self.context)
            else:
                err_msg = "Not a top-level function: {}".format(function_name)
                if function_name in self.context.sigs['self']:
                    err_msg += ". Did you mean self.{}?".format(function_name)
                raise StructureException(err_msg, self.expr)
        elif isinstance(self.expr.func, ast.Attribute) and isinstance(self.expr.func.value, ast.Name) and self.expr.func.value.id == "self":
            method_name = self.expr.func.attr
            if method_name not in self.context.sigs['self']:
                raise VariableDeclarationException("Function not declared yet (reminder: functions cannot "
                                                   "call functions later in code than themselves): %s" % self.expr.func.attr)
            sig = self.context.sigs['self'][self.expr.func.attr]
            add_gas = self.context.sigs['self'][method_name].gas  # gas of call
            inargs, inargsize = pack_arguments(sig, [Expr(arg, self.context).lll_node for arg in self.expr.args], self.context)
            output_placeholder = self.context.new_placeholder(typ=sig.output_type)
            if isinstance(sig.output_type, BaseType):
                returner = output_placeholder
            elif isinstance(sig.output_type, ByteArrayType):
                returner = output_placeholder + 32
            else:
                raise TypeMismatchException("Invalid output type: %r" % sig.output_type, self.expr)
            o = LLLnode.from_list(['seq',
                                        ['assert', ['call', ['gas'], ['address'], 0,
                                                        inargs, inargsize,
                                                        output_placeholder, get_size_of_type(sig.output_type) * 32]],
                                        returner], typ=sig.output_type, location='memory',
                                        pos=getpos(self.expr), add_gas_estimate=add_gas, annotation='Internal Call: %s' % method_name)
            o.gas += sig.gas
            return o
        elif isinstance(self.expr.func, ast.Attribute) and isinstance(self.expr.func.value, ast.Call):
            contract_name = self.expr.func.value.func.id
            contract_address = Expr.parse_value_expr(self.expr.func.value.args[0], self.context)
            return external_contract_call_expr(self.expr, self.context, contract_name, contract_address)
        elif isinstance(self.expr.func.value, ast.Attribute) and self.expr.func.value.attr in self.context.sigs:
            contract_name = self.expr.func.value.attr
            var = self.context.globals[self.expr.func.value.attr]
            contract_address = unwrap_location(LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(self.expr), annotation='self.' + self.expr.func.value.attr))
            return external_contract_call_expr(self.expr, self.context, contract_name, contract_address)
        elif isinstance(self.expr.func.value, ast.Attribute) and self.expr.func.value.attr in self.context.globals:
            contract_name = self.context.globals[self.expr.func.value.attr].typ.unit
            var = self.context.globals[self.expr.func.value.attr]
            contract_address = unwrap_location(LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(self.expr), annotation='self.' + self.expr.func.value.attr))
            return external_contract_call_expr(self.expr, self.context, contract_name, contract_address)
        else:
            raise StructureException("Unsupported operator: %r" % ast.dump(self.expr), self.expr)

    def list_literals(self):
        if not len(self.expr.elts):
            raise StructureException("List must have elements", self.expr)
        o = []
        out_type = None
        for elt in self.expr.elts:
            o.append(Expr(elt, self.context).lll_node)
            if not out_type:
                out_type = o[-1].typ
            previous_type = o[-1].typ.subtype.typ if hasattr(o[-1].typ, 'subtype') else o[-1].typ
            current_type = out_type.subtype.typ if hasattr(out_type, 'subtype') else out_type
            if len(o) > 1 and previous_type != current_type:
                raise TypeMismatchException("Lists may only contain one type", self.expr)
        return LLLnode.from_list(["multi"] + o, typ=ListType(out_type, len(o)), pos=getpos(self.expr))

    def struct_literals(self):
        o = {}
        members = {}
        for key, value in zip(self.expr.keys, self.expr.values):
            if not isinstance(key, ast.Name) or not is_varname_valid(key.id):
                raise TypeMismatchException("Invalid member variable for struct: %r" % vars(key).get('id', key), key)
            if key.id in o:
                raise TypeMismatchException("Member variable duplicated: " + key.id, key)
            o[key.id] = Expr(value, self.context).lll_node
            members[key.id] = o[key.id].typ
        return LLLnode.from_list(["multi"] + [o[key] for key in sorted(list(o.keys()))], typ=StructType(members), pos=getpos(self.expr))

    def tuple_literals(self):
        if not len(self.expr.elts):
            raise StructureException("Tuple must have elements", self.expr)
        o = []
        for elt in self.expr.elts:
            o.append(Expr(elt, self.context).lll_node)
        return LLLnode.from_list(["multi"] + o, typ=TupleType(o), pos=getpos(self.expr))

    # Parse an expression that results in a value
    def parse_value_expr(expr, context):
        return unwrap_location(Expr(expr, context).lll_node)

    # Parse an expression that represents an address in memory or storage
    def parse_variable_location(expr, context):
        o = Expr(expr, context).lll_node
        if not o.location:
            raise Exception("Looking for a variable location, instead got a value")
        return o
