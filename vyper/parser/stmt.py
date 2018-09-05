import ast
import re

from vyper.exceptions import (
    ConstancyViolationException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
    EventDeclarationException,
    InvalidLiteralException
)
from vyper.functions import (
    stmt_dispatch_table,
    dispatch_table
)
from vyper.parser.parser_utils import LLLnode
from vyper.parser.parser_utils import (
    getpos,
    make_byte_array_copier,
    base_type_conversion,
    unwrap_location
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    TupleType,
    StructType,
    NullType
)
from vyper.types import (
    get_size_of_type,
    is_base_type,
    parse_type,
    NodeType
)
from vyper.types import (
    are_units_compatible,
)
from vyper.utils import (
    SizeLimits,
    sha3,
    fourbytes_to_int
)
from vyper.parser.expr import (
    Expr
)
from vyper.signatures.function_signature import FunctionSignature


class Stmt(object):
    # TODO: Once other refactors are made reevaluate all inline imports
    def __init__(self, stmt, context):
        self.stmt = stmt
        self.context = context
        self.stmt_table = {
            ast.Expr: self.expr,
            ast.Pass: self.parse_pass,
            ast.AnnAssign: self.ann_assign,
            ast.Assign: self.assign,
            ast.If: self.parse_if,
            ast.Call: self.call,
            ast.Assert: self.parse_assert,
            ast.For: self.parse_for,
            ast.AugAssign: self.aug_assign,
            ast.Break: self.parse_break,
            ast.Continue: self.parse_continue,
            ast.Return: self.parse_return,
            ast.Delete: self.parse_delete,
            ast.Str: self.parse_docblock,  # docblock
            ast.Name: self.parse_name,
        }
        stmt_type = self.stmt.__class__
        if stmt_type in self.stmt_table:
            self.lll_node = self.stmt_table[stmt_type]()
        else:
            raise StructureException("Unsupported statement type: %s" % type(stmt), stmt)

    def expr(self):
        return Stmt(self.stmt.value, self.context).lll_node

    def parse_pass(self):
        return LLLnode.from_list('pass', typ=None, pos=getpos(self.stmt))

    def parse_name(self):
        if self.stmt.id == "vdb":
            return LLLnode('debugger', typ=None, pos=getpos(self.stmt))
        elif self.stmt.id == "throw":
            return LLLnode.from_list(['assert', 0], typ=None, pos=getpos(self.stmt))
        else:
            raise StructureException("Unsupported statement type: %s" % type(self.stmt), self.stmt)

    def _check_valid_assign(self, sub):
        if isinstance(self.stmt.annotation, ast.Call):  # unit style: num(wei)
            if self.stmt.annotation.func.id != sub.typ.typ and not sub.typ.is_literal:
                raise TypeMismatchException('Invalid type, expected: %s' % self.stmt.annotation.func.id, self.stmt)
        elif isinstance(self.stmt.annotation, ast.Dict):
            if not isinstance(sub.typ, StructType):
                raise TypeMismatchException('Invalid type, expected a struct')
        elif isinstance(self.stmt.annotation, ast.Subscript):
            if not isinstance(sub.typ, (ListType, ByteArrayType)):  # check list assign.
                raise TypeMismatchException('Invalid type, expected: %s' % self.stmt.annotation.value.id, self.stmt)
        # Check that the integer literal, can be assigned to uint256 if necessary.
        elif (self.stmt.annotation.id, sub.typ.typ) == ('uint256', 'int128') and sub.typ.is_literal:
            if not SizeLimits.in_bounds('uint256', sub.value):
                raise InvalidLiteralException('Invalid uint256 assignment, value not in uint256 range.', self.stmt)
        elif self.stmt.annotation.id != sub.typ.typ and not sub.typ.unit:
            raise TypeMismatchException('Invalid type, expected: %s' % self.stmt.annotation.id, self.stmt)

    def ann_assign(self):
        from .parser import (
            make_setter,
        )
        self.context.set_in_assignment(True)
        typ = parse_type(self.stmt.annotation, location='memory', custom_units=self.context.custom_units)
        if isinstance(self.stmt.target, ast.Attribute) and self.stmt.target.value.id == 'self':
            raise TypeMismatchException('May not redefine storage variables.', self.stmt)
        varname = self.stmt.target.id
        pos = self.context.new_variable(varname, typ)
        o = LLLnode.from_list('pass', typ=None, pos=pos)
        if self.stmt.value is not None:
            sub = Expr(self.stmt.value, self.context).lll_node
            self._check_valid_assign(sub)
            variable_loc = LLLnode.from_list(pos, typ=typ, location='memory', pos=getpos(self.stmt))
            o = make_setter(variable_loc, sub, 'memory', pos=getpos(self.stmt))
        self.context.set_in_assignment(False)
        return o

    def assign(self):
        from .parser import (
            make_setter,
        )
        # Assignment (e.g. x[4] = y)
        if len(self.stmt.targets) != 1:
            raise StructureException("Assignment statement must have one target", self.stmt)
        self.context.set_in_assignment(True)
        sub = Expr(self.stmt.value, self.context).lll_node
        # Determine if it's an RLPList assignment.
        if isinstance(self.stmt.value, ast.Call) and getattr(self.stmt.value.func, 'id', '') is 'RLPList':
            pos = self.context.new_variable(self.stmt.targets[0].id, sub.typ)
            variable_loc = LLLnode.from_list(pos, typ=sub.typ, location='memory', pos=getpos(self.stmt), annotation=self.stmt.targets[0].id)
            o = make_setter(variable_loc, sub, 'memory', pos=getpos(self.stmt))
        # All other assignments are forbidden.
        elif isinstance(self.stmt.targets[0], ast.Name) and self.stmt.targets[0].id not in self.context.vars:
            raise VariableDeclarationException("Variable type not defined", self.stmt)
        elif isinstance(self.stmt.targets[0], ast.Tuple) and isinstance(self.stmt.value, ast.Tuple):
            raise VariableDeclarationException("Tuple to tuple assignment not supported", self.stmt)
        else:
            # Checks to see if assignment is valid
            target = self.get_target(self.stmt.targets[0])
            o = make_setter(target, sub, target.location, pos=getpos(self.stmt))
        o.pos = getpos(self.stmt)
        self.context.set_in_assignment(False)
        return o

    def parse_if(self):
        from .parser import (
            parse_body,
        )
        if self.stmt.orelse:
            block_scope_id = id(self.stmt.orelse)
            self.context.start_blockscope(block_scope_id)
            add_on = [parse_body(self.stmt.orelse, self.context)]
            self.context.end_blockscope(block_scope_id)
        else:
            add_on = []

        block_scope_id = id(self.stmt)
        self.context.start_blockscope(block_scope_id)
        o = LLLnode.from_list(
            ['if', Expr.parse_value_expr(self.stmt.test, self.context), parse_body(self.stmt.body, self.context)] + add_on,
            typ=None, pos=getpos(self.stmt)
        )
        self.context.end_blockscope(block_scope_id)
        return o

    def call(self):
        from .parser import (
            pack_arguments,
            pack_logging_data,
            pack_logging_topics,
            external_contract_call,
        )
        if isinstance(self.stmt.func, ast.Name):
            if self.stmt.func.id in stmt_dispatch_table:
                return stmt_dispatch_table[self.stmt.func.id](self.stmt, self.context)
            elif self.stmt.func.id in dispatch_table:
                raise StructureException("Function {} can not be called without being used.".format(self.stmt.func.id), self.stmt)
            else:
                raise StructureException("Unknown function: '{}'.".format(self.stmt.func.id), self.stmt)
        elif isinstance(self.stmt.func, ast.Attribute) and isinstance(self.stmt.func.value, ast.Name) and self.stmt.func.value.id == "self":
            method_name = self.stmt.func.attr
            expr_args = [Expr(arg, self.context).lll_node for arg in self.stmt.args]
            # full_sig = FunctionSignature.get_full_sig(method_name, expr_args, self.context.sigs, self.context.custom_units)
            sig = FunctionSignature.lookup_sig(self.context.sigs, method_name, expr_args, self.stmt, self.context)
            if self.context.is_constant and not sig.const:
                raise ConstancyViolationException(
                    "May not call non-constant function '%s' within a constant function." % (sig.sig)
                )
            add_gas = self.context.sigs['self'][sig.sig].gas
            inargs, inargsize = pack_arguments(sig,
                                                expr_args,
                                                self.context, pos=getpos(self.stmt))
            return LLLnode.from_list(['assert', ['call', ['gas'], ['address'], 0, inargs, inargsize, 0, 0]],
                                        typ=None, pos=getpos(self.stmt), add_gas_estimate=add_gas, annotation='Internal Call: %s' % sig.sig)
        elif isinstance(self.stmt.func, ast.Attribute) and isinstance(self.stmt.func.value, ast.Call):
            contract_name = self.stmt.func.value.func.id
            contract_address = Expr.parse_value_expr(self.stmt.func.value.args[0], self.context)
            return external_contract_call(self.stmt, self.context, contract_name, contract_address, pos=getpos(self.stmt))
        elif isinstance(self.stmt.func.value, ast.Attribute) and self.stmt.func.value.attr in self.context.sigs:
            contract_name = self.stmt.func.value.attr
            var = self.context.globals[self.stmt.func.value.attr]
            contract_address = unwrap_location(LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(self.stmt), annotation='self.' + self.stmt.func.value.attr))
            return external_contract_call(self.stmt, self.context, contract_name, contract_address, pos=getpos(self.stmt))
        elif isinstance(self.stmt.func.value, ast.Attribute) and self.stmt.func.value.attr in self.context.globals:
            contract_name = self.context.globals[self.stmt.func.value.attr].typ.unit
            var = self.context.globals[self.stmt.func.value.attr]
            contract_address = unwrap_location(LLLnode.from_list(var.pos, typ=var.typ, location='storage', pos=getpos(self.stmt), annotation='self.' + self.stmt.func.value.attr))
            return external_contract_call(self.stmt, self.context, contract_name, contract_address, pos=getpos(self.stmt))
        elif isinstance(self.stmt.func, ast.Attribute) and self.stmt.func.value.id == 'log':
            if self.stmt.func.attr not in self.context.sigs['self']:
                raise EventDeclarationException("Event not declared yet: %s" % self.stmt.func.attr)
            event = self.context.sigs['self'][self.stmt.func.attr]
            if len(event.indexed_list) != len(self.stmt.args):
                raise EventDeclarationException("%s received %s arguments but expected %s" % (event.name, len(self.stmt.args), len(event.indexed_list)))
            expected_topics, topics = [], []
            expected_data, data = [], []
            for pos, is_indexed in enumerate(event.indexed_list):
                if is_indexed:
                    expected_topics.append(event.args[pos])
                    topics.append(self.stmt.args[pos])
                else:
                    expected_data.append(event.args[pos])
                    data.append(self.stmt.args[pos])
            topics = pack_logging_topics(event.event_id, topics, expected_topics, self.context, pos=getpos(self.stmt))
            inargs, inargsize, inargsize_node, inarg_start = pack_logging_data(expected_data, data, self.context, pos=getpos(self.stmt))

            if inargsize_node is None:
                sz = inargsize
            else:
                sz = ['mload', inargsize_node]

            return LLLnode.from_list(['seq', inargs,
                LLLnode.from_list(["log" + str(len(topics)), inarg_start, sz] + topics, add_gas_estimate=inargsize * 10)], typ=None, pos=getpos(self.stmt))
        else:
            raise StructureException("Unsupported operator: %r" % ast.dump(self.stmt), self.stmt)

    def parse_assert(self):
        if self.stmt.msg:
            if len(self.stmt.msg.s.strip()) == 0:
                raise StructureException('Empty reason string not allowed.', self.stmt)
            reason_str = self.stmt.msg.s.strip()
            sig_placeholder = self.context.new_placeholder(BaseType(32))
            arg_placeholder = self.context.new_placeholder(BaseType(32))
            reason_str_type = ByteArrayType(len(reason_str))
            placeholder_bytes = Expr(self.stmt.msg, self.context).lll_node
            method_id = fourbytes_to_int(sha3(b"Error(string)")[:4])
            assert_reason = \
                ['seq',
                    ['mstore', sig_placeholder, method_id],
                    ['mstore', arg_placeholder, 32],
                    placeholder_bytes,
                    ['assert_reason', Expr.parse_value_expr(self.stmt.test, self.context), int(sig_placeholder + 28), int(4 + 32 + get_size_of_type(reason_str_type) * 32)]]
            return LLLnode.from_list(assert_reason, typ=None, pos=getpos(self.stmt))
        else:
            return LLLnode.from_list(['assert', Expr.parse_value_expr(self.stmt.test, self.context)], typ=None, pos=getpos(self.stmt))

    def parse_for(self):
        from .parser import (
            parse_body,
        )
        # Type 0 for, e.g. for i in list(): ...
        if self._is_list_iter():
            return self.parse_for_list()

        if not isinstance(self.stmt.iter, ast.Call) or \
            not isinstance(self.stmt.iter.func, ast.Name) or \
                not isinstance(self.stmt.target, ast.Name) or \
                    self.stmt.iter.func.id != "range" or \
                        len(self.stmt.iter.args) not in (1, 2):
            raise StructureException("For statements must be of the form `for i in range(rounds): ..` or `for i in range(start, start + rounds): ..`", self.stmt.iter)  # noqa

        block_scope_id = id(self.stmt.orelse)
        self.context.start_blockscope(block_scope_id)
        # Type 1 for, e.g. for i in range(10): ...
        if len(self.stmt.iter.args) == 1:
            if not isinstance(self.stmt.iter.args[0], ast.Num):
                raise StructureException("Range only accepts literal values", self.stmt.iter)
            start = LLLnode.from_list(0, typ='int128', pos=getpos(self.stmt))
            rounds = self.stmt.iter.args[0].n
        elif isinstance(self.stmt.iter.args[0], ast.Num) and isinstance(self.stmt.iter.args[1], ast.Num):
            # Type 2 for, e.g. for i in range(100, 110): ...
            start = LLLnode.from_list(self.stmt.iter.args[0].n, typ='int128', pos=getpos(self.stmt))
            rounds = LLLnode.from_list(self.stmt.iter.args[1].n - self.stmt.iter.args[0].n, typ='int128', pos=getpos(self.stmt))
        else:
            # Type 3 for, e.g. for i in range(x, x + 10): ...
            if not isinstance(self.stmt.iter.args[1], ast.BinOp) or not isinstance(self.stmt.iter.args[1].op, ast.Add):
                raise StructureException("Two-arg for statements must be of the form `for i in range(start, start + rounds): ...`",
                                            self.stmt.iter.args[1])
            if ast.dump(self.stmt.iter.args[0]) != ast.dump(self.stmt.iter.args[1].left):
                raise StructureException("Two-arg for statements of the form `for i in range(x, x + y): ...` must have x identical in both places: %r %r" % (ast.dump(self.stmt.iter.args[0]), ast.dump(self.stmt.iter.args[1].left)), self.stmt.iter)
            if not isinstance(self.stmt.iter.args[1].right, ast.Num):
                raise StructureException("Range only accepts literal values", self.stmt.iter.args[1])
            start = Expr.parse_value_expr(self.stmt.iter.args[0], self.context)
            rounds = self.stmt.iter.args[1].right.n
        varname = self.stmt.target.id
        pos = self.context.new_variable(varname, BaseType('int128'))
        self.context.forvars[varname] = True
        o = LLLnode.from_list(['repeat', pos, start, rounds, parse_body(self.stmt.body, self.context)], typ=None, pos=getpos(self.stmt))
        del self.context.vars[varname]
        del self.context.forvars[varname]
        self.context.end_blockscope(block_scope_id)
        return o

    def _is_list_iter(self):
        """
        Test if the current statement is a type of list, used in for loops.
        """

        # Check for literal or memory list.
        iter_var_type = self.context.vars.get(self.stmt.iter.id).typ if isinstance(self.stmt.iter, ast.Name) else None
        if isinstance(self.stmt.iter, ast.List) or isinstance(iter_var_type, ListType):
            return True

        # Check for storage list.
        if isinstance(self.stmt.iter, ast.Attribute):
            iter_var_type = self.context.globals.get(self.stmt.iter.attr)
            if iter_var_type and isinstance(iter_var_type.typ, ListType):
                return True

        return False

    def parse_for_list(self):
        from .parser import (
            parse_body,
            make_setter
        )

        iter_list_node = Expr(self.stmt.iter, self.context).lll_node
        if not isinstance(iter_list_node.typ.subtype, BaseType):  # Sanity check on list subtype.
            raise StructureException('For loops allowed only on basetype lists.', self.stmt.iter)
        iter_var_type = self.context.vars.get(self.stmt.iter.id).typ if isinstance(self.stmt.iter, ast.Name) else None
        subtype = iter_list_node.typ.subtype.typ
        varname = self.stmt.target.id
        value_pos = self.context.new_variable(varname, BaseType(subtype))
        i_pos = self.context.new_variable('_index_for_' + varname, BaseType(subtype))
        self.context.forvars[varname] = True
        if iter_var_type:  # Is a list that is already allocated to memory.
            self.context.set_in_for_loop(self.stmt.iter.id)  # make sure list cannot be altered whilst iterating.
            iter_var = self.context.vars.get(self.stmt.iter.id)
            body = [
                'seq',
                ['mstore', value_pos, ['mload', ['add', iter_var.pos, ['mul', ['mload', i_pos], 32]]]],
                parse_body(self.stmt.body, self.context)
            ]
            o = LLLnode.from_list(
                ['repeat', i_pos, 0, iter_var.size, body], typ=None, pos=getpos(self.stmt)
            )
            self.context.remove_in_for_loop(self.stmt.iter.id)
        elif isinstance(self.stmt.iter, ast.List):  # List gets defined in the for statement.
            # Allocate list to memory.
            count = iter_list_node.typ.count
            tmp_list = LLLnode.from_list(
                obj=self.context.new_placeholder(ListType(iter_list_node.typ.subtype, count)),
                typ=ListType(iter_list_node.typ.subtype, count),
                location='memory'
            )
            setter = make_setter(tmp_list, iter_list_node, 'memory', pos=getpos(self.stmt))
            body = [
                'seq',
                ['mstore', value_pos, ['mload', ['add', tmp_list, ['mul', ['mload', i_pos], 32]]]],
                parse_body(self.stmt.body, self.context)
            ]
            o = LLLnode.from_list(
                ['seq',
                    setter,
                    ['repeat', i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
            )
        elif isinstance(self.stmt.iter, ast.Attribute):  # List is contained in storage.
            count = iter_list_node.typ.count
            self.context.set_in_for_loop(iter_list_node.annotation)  # make sure list cannot be altered whilst iterating.
            body = [
                'seq',
                ['mstore', value_pos, ['sload', ['add', ['sha3_32', iter_list_node], ['mload', i_pos]]]],
                parse_body(self.stmt.body, self.context),
            ]
            o = LLLnode.from_list(
                ['seq',
                    ['repeat', i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
            )
            self.context.remove_in_for_loop(iter_list_node.annotation)
        del self.context.vars[varname]
        del self.context.vars['_index_for_' + varname]
        del self.context.forvars[varname]
        return o

    def aug_assign(self):
        target = self.get_target(self.stmt.target)
        sub = Expr.parse_value_expr(self.stmt.value, self.context)
        if not isinstance(self.stmt.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            raise Exception("Unsupported operator for augassign")
        if not isinstance(target.typ, BaseType):
            raise TypeMismatchException("Can only use aug-assign operators with simple types!", self.stmt.target)
        if target.location == 'storage':
            o = Expr.parse_value_expr(ast.BinOp(left=LLLnode.from_list(['sload', '_stloc'], typ=target.typ, pos=target.pos),
                                    right=sub, op=self.stmt.op, lineno=self.stmt.lineno, col_offset=self.stmt.col_offset), self.context)
            return LLLnode.from_list(['with', '_stloc', target, ['sstore', '_stloc', base_type_conversion(o, o.typ, target.typ, pos=getpos(self.stmt))]], typ=None, pos=getpos(self.stmt))
        elif target.location == 'memory':
            o = Expr.parse_value_expr(ast.BinOp(left=LLLnode.from_list(['mload', '_mloc'], typ=target.typ, pos=target.pos),
                                    right=sub, op=self.stmt.op, lineno=self.stmt.lineno, col_offset=self.stmt.col_offset), self.context)
            return LLLnode.from_list(['with', '_mloc', target, ['mstore', '_mloc', base_type_conversion(o, o.typ, target.typ, pos=getpos(self.stmt))]], typ=None, pos=getpos(self.stmt))

    def parse_continue(self):
        return LLLnode.from_list('continue', typ=None, pos=getpos(self.stmt))

    def parse_break(self):
        return LLLnode.from_list('break', typ=None, pos=getpos(self.stmt))

    def parse_return(self):
        from .parser import (
            make_setter
        )
        if self.context.return_type is None:
            if self.stmt.value:
                raise TypeMismatchException("Not expecting to return a value", self.stmt)
            return LLLnode.from_list(['return', 0, 0], typ=None, pos=getpos(self.stmt))
        if not self.stmt.value:
            raise TypeMismatchException("Expecting to return a value", self.stmt)

        sub = Expr(self.stmt.value, self.context).lll_node
        self.context.increment_return_counter()
        # Returning a value (most common case)
        if isinstance(sub.typ, BaseType):
            if not isinstance(self.context.return_type, BaseType):
                raise TypeMismatchException("Trying to return base type %r, output expecting %r" % (sub.typ, self.context.return_type), self.stmt.value)
            sub = unwrap_location(sub)
            if not are_units_compatible(sub.typ, self.context.return_type):
                raise TypeMismatchException("Return type units mismatch %r %r" % (sub.typ, self.context.return_type), self.stmt.value)
            elif sub.typ.is_literal and (self.context.return_type.typ == sub.typ or
                    'int' in self.context.return_type.typ and
                    'int' in sub.typ.typ):
                if not SizeLimits.in_bounds(self.context.return_type.typ, sub.value):
                    raise InvalidLiteralException("Number out of range: " + str(sub.value), self.stmt)
                return LLLnode.from_list(['seq', ['mstore', 0, sub], ['return', 0, 32]], typ=None, pos=getpos(self.stmt))
            elif is_base_type(sub.typ, self.context.return_type.typ) or \
                    (is_base_type(sub.typ, 'int128') and is_base_type(self.context.return_type, 'int256')):
                return LLLnode.from_list(['seq', ['mstore', 0, sub], ['return', 0, 32]], typ=None, pos=getpos(self.stmt))
            else:
                raise TypeMismatchException("Unsupported type conversion: %r to %r" % (sub.typ, self.context.return_type), self.stmt.value)
        # Returning a byte array
        elif isinstance(sub.typ, ByteArrayType):
            if not isinstance(self.context.return_type, ByteArrayType):
                raise TypeMismatchException("Trying to return base type %r, output expecting %r" % (sub.typ, self.context.return_type), self.stmt.value)
            if sub.typ.maxlen > self.context.return_type.maxlen:
                raise TypeMismatchException("Cannot cast from greater max-length %d to shorter max-length %d" %
                                            (sub.typ.maxlen, self.context.return_type.maxlen), self.stmt.value)

            zero_padder = LLLnode.from_list(['pass'])
            if sub.typ.maxlen > 0:
                zero_pad_i = self.context.new_placeholder(BaseType('uint256'))  # Iterator used to zero pad memory.
                zero_padder = LLLnode.from_list(
                    ['repeat', zero_pad_i, ['mload', '_loc'], sub.typ.maxlen,
                        ['seq',
                            ['if', ['gt', ['mload', zero_pad_i], sub.typ.maxlen], 'break'],  # stay within allocated bounds
                            ['mstore8', ['add', ['add', 32, '_loc'], ['mload', zero_pad_i]], 0]]],
                    annotation="Zero pad"
                )

            # Returning something already in memory
            if sub.location == 'memory':
                return LLLnode.from_list(
                    ['with', '_loc', sub,
                        ['seq',
                            ['mstore', ['sub', '_loc', 32], 32],
                            zero_padder,
                            ['return', ['sub', '_loc', 32], ['ceil32', ['add', ['mload', '_loc'], 64]]]]], typ=None, pos=getpos(self.stmt))

            # Copying from storage
            elif sub.location == 'storage':
                # Instantiate a byte array at some index
                fake_byte_array = LLLnode(self.context.get_next_mem() + 32, typ=sub.typ, location='memory', pos=getpos(self.stmt))
                o = [
                    'with', '_loc', self.context.get_next_mem() + 32,
                    ['seq',
                        # Copy the data to this byte array
                        make_byte_array_copier(fake_byte_array, sub),
                        # Store the number 32 before it for ABI formatting purposes
                        ['mstore', self.context.get_next_mem(), 32],
                        zero_padder,
                        # Return it
                        ['return', self.context.get_next_mem(), ['add', ['ceil32', ['mload', self.context.get_next_mem() + 32]], 64]]]
                ]
                return LLLnode.from_list(o, typ=None, pos=getpos(self.stmt))
            else:
                raise Exception("Invalid location: %s" % sub.location)

        elif isinstance(sub.typ, ListType):
            sub_base_type = re.split(r'\(|\[', str(sub.typ.subtype))[0]
            ret_base_type = re.split(r'\(|\[', str(self.context.return_type.subtype))[0]
            if sub_base_type != ret_base_type:
                raise TypeMismatchException(
                    "List return type %r does not match specified return type, expecting %r" % (
                        sub_base_type, ret_base_type
                    ),
                    self.stmt
                )
            elif sub.location == "memory" and sub.value != "multi":
                return LLLnode.from_list(['return', sub, get_size_of_type(self.context.return_type) * 32],
                                            typ=None, pos=getpos(self.stmt))
            else:
                new_sub = LLLnode.from_list(self.context.new_placeholder(self.context.return_type), typ=self.context.return_type, location='memory')
                setter = make_setter(new_sub, sub, 'memory', pos=getpos(self.stmt))
                return LLLnode.from_list(['seq', setter, ['return', new_sub, get_size_of_type(self.context.return_type) * 32]],
                                            typ=None, pos=getpos(self.stmt))

        # Returning a tuple.
        elif isinstance(sub.typ, TupleType):
            if len(self.context.return_type.members) != len(sub.typ.members):
                raise StructureException("Tuple lengths don't match!", self.stmt)
            # check return type matches, sub type.
            for i, ret_x in enumerate(self.context.return_type.members):
                s_member = sub.typ.members[i]
                sub_type = s_member if isinstance(s_member, NodeType) else s_member.typ
                if type(sub_type) is not type(ret_x):
                    raise StructureException(
                        "Tuple return type does not match annotated return. {} != {}".format(
                            type(sub_type), type(ret_x)
                        ),
                        self.stmt
                    )
            # Is from a call expression.
            if len(sub.args[0].args) > 0 and sub.args[0].args[0].value == 'call':
                mem_pos = sub.args[0].args[-1]
                mem_size = get_size_of_type(sub.typ) * 32
                return LLLnode.from_list(['return', mem_pos, mem_size], typ=sub.typ)
            subs = []
            dynamic_offset_counter = LLLnode(self.context.get_next_mem(), typ=None, annotation="dynamic_offset_counter")  # dynamic offset position counter.
            new_sub = LLLnode.from_list(self.context.get_next_mem() + 32, typ=self.context.return_type, location='memory', annotation='new_sub')
            keyz = list(range(len(sub.typ.members)))
            dynamic_offset_start = 32 * len(sub.args)  # The static list of args end.
            left_token = LLLnode.from_list('_loc', typ=new_sub.typ, location="memory")

            def get_dynamic_offset_value():
                # Get value of dynamic offset counter.
                return ['mload', dynamic_offset_counter]

            def increment_dynamic_offset(dynamic_spot):
                # Increment dyanmic offset counter in memory.
                return ['mstore', dynamic_offset_counter,
                                 ['add',
                                        ['add', ['ceil32', ['mload', dynamic_spot]], 32],
                                        ['mload', dynamic_offset_counter]]]

            for i, typ in enumerate(keyz):
                arg = sub.args[i]
                variable_offset = LLLnode.from_list(['add', 32 * i, left_token], typ=arg.typ, annotation='variable_offset')
                if isinstance(arg.typ, ByteArrayType):
                    # Store offset pointer value.
                    subs.append(['mstore', variable_offset, get_dynamic_offset_value()])

                    # Store dynamic data, from offset pointer onwards.
                    dynamic_spot = LLLnode.from_list(['add', left_token, get_dynamic_offset_value()], location="memory", typ=arg.typ, annotation='dynamic_spot')
                    subs.append(make_setter(dynamic_spot, arg, location="memory", pos=getpos(self.stmt)))
                    subs.append(increment_dynamic_offset(dynamic_spot))

                elif isinstance(arg.typ, BaseType):
                    subs.append(make_setter(variable_offset, arg, "memory", pos=getpos(self.stmt)))
                else:
                    raise Exception("Can't return type %s as part of tuple", type(arg.typ))

            setter = LLLnode.from_list(['seq',
                ['mstore', dynamic_offset_counter, dynamic_offset_start],
                ['with', '_loc', new_sub, ['seq'] + subs]], typ=None
            )

            return LLLnode.from_list(['seq', setter, ['return', new_sub, get_dynamic_offset_value()]],
                                        typ=None, pos=getpos(self.stmt))
        else:
            raise TypeMismatchException("Can only return base type!", self.stmt)

    def parse_delete(self):
        from .parser import (
            make_setter,
        )
        if len(self.stmt.targets) != 1:
            raise StructureException("Can delete one variable at a time", self.stmt)
        target = self.stmt.targets[0]
        target_lll = Expr(self.stmt.targets[0], self.context).lll_node

        if isinstance(target, ast.Subscript):
            if target_lll.location == "storage":
                return make_setter(target_lll, LLLnode.from_list(None, typ=NullType()), "storage", pos=getpos(self.stmt))

        raise StructureException("Deleting type not supported.", self.stmt)

    def get_target(self, target):
        if isinstance(target, ast.Subscript) and self.context.in_for_loop:  # Check if we are doing assignment of an iteration loop.
            raise_exception = False
            if isinstance(target.value, ast.Attribute):
                list_name = "%s.%s" % (target.value.value.id, target.value.attr)
                if list_name in self.context.in_for_loop:
                    raise_exception = True

            if isinstance(target.value, ast.Name) and \
               target.value.id in self.context.in_for_loop:
                list_name = target.value.id
                raise_exception = True

            if raise_exception:
                raise StructureException("Altering list '%s' which is being iterated!" % list_name, self.stmt)

        if isinstance(target, ast.Name) and target.id in self.context.forvars:
            raise StructureException("Altering iterator '%s' which is in use!" % target.id, self.stmt)
        if isinstance(target, ast.Tuple):
            return Expr(target, self.context).lll_node
        target = Expr.parse_variable_location(target, self.context)
        if target.location == 'storage' and self.context.is_constant:
            raise ConstancyViolationException("Cannot modify storage inside a constant function: %s" % target.annotation)
        if not target.mutable:
            raise ConstancyViolationException("Cannot modify function argument: %s" % target.annotation)
        return target

    def parse_docblock(self):
        if '"""' not in self.context.origcode.splitlines()[self.stmt.lineno - 1]:
            raise InvalidLiteralException('Only valid """ docblocks allowed', self.stmt)
        return LLLnode.from_list('pass', typ=None, pos=getpos(self.stmt))
