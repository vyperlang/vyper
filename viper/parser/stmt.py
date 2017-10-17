import ast

from viper.exceptions import (
    ConstancyViolationException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)
from viper.functions import (
    stmt_dispatch_table,
)
from .parser_utils import LLLnode
from .parser_utils import (
    add_variable_offset,
    getpos,
    make_byte_array_copier,
    base_type_conversion,
    unwrap_location
)
from viper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    TupleType
)
from viper.types import (
    get_size_of_type,
    is_base_type,
    parse_type,
)
from viper.types import (
    are_units_compatible,
    set_default_units,
)


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
            ast.Return: self.parse_return,
        }
        stmt_type = self.stmt.__class__
        if stmt_type in self.stmt_table:
            self.lll_node = self.stmt_table[stmt_type]()
        elif isinstance(stmt, ast.Name) and stmt.id == "throw":
            self.lll_node = LLLnode.from_list(['assert', 0], typ=None, pos=getpos(stmt))
        else:
            raise StructureException("Unsupported statement type", stmt)

    def expr(self):
        return Stmt(self.stmt.value, self.context).lll_node

    def parse_pass(self):
        return LLLnode.from_list('pass', typ=None, pos=getpos(self.stmt))

    def ann_assign(self):
        typ = parse_type(self.stmt.annotation, location='memory')
        varname = self.stmt.target.id
        pos = self.context.new_variable(varname, typ)
        return LLLnode.from_list('pass', typ=None, pos=pos)

    def assign(self):
        from .parser import (
            parse_expr,
            parse_variable_location,
            make_setter,
        )
        # Assignment (eg. x[4] = y)
        if len(self.stmt.targets) != 1:
            raise StructureException("Assignment statement must have one target", self.stmt)
        sub = parse_expr(self.stmt.value, self.context)
        if isinstance(self.stmt.targets[0], ast.Name) and self.stmt.targets[0].id not in self.context.vars:
            pos = self.context.new_variable(self.stmt.targets[0].id, set_default_units(sub.typ))
            variable_loc = LLLnode.from_list(pos, typ=sub.typ, location='memory', pos=getpos(self.stmt), annotation=self.stmt.targets[0].id)
            o = make_setter(variable_loc, sub, 'memory')
        else:
            target = parse_variable_location(self.stmt.targets[0], self.context)
            if target.location == 'storage' and self.context.is_constant:
                raise ConstancyViolationException("Cannot modify storage inside a constant function!", self.stmt.targets[0])
            if not target.mutable:
                raise ConstancyViolationException("Cannot modify function argument", self.stmt.targets[0])
            o = make_setter(target, sub, target.location)
        o.pos = getpos(self.stmt)
        return o

    def parse_if(self):
        from .parser import (
            parse_value_expr,
            parse_body,
        )
        if self.stmt.orelse:
            add_on = [parse_body(self.stmt.orelse, self.context)]
        else:
            add_on = []
        return LLLnode.from_list(['if', parse_value_expr(self.stmt.test, self.context), parse_body(self.stmt.body, self.context)] + add_on, typ=None, pos=getpos(self.stmt))

    def call(self):
        from .parser import (
            parse_expr,
            pack_arguments,
            pack_logging_data,
            pack_logging_topics,
            external_contract_call_stmt,
        )
        if isinstance(self.stmt.func, ast.Name) and self.stmt.func.id in stmt_dispatch_table:
                return stmt_dispatch_table[self.stmt.func.id](self.stmt, self.context)
        elif isinstance(self.stmt.func, ast.Attribute) and isinstance(self.stmt.func.value, ast.Name) and self.stmt.func.value.id == "self":
            if self.stmt.func.attr not in self.context.sigs['self']:
                raise VariableDeclarationException("Function not declared yet (reminder: functions cannot "
                                                    "call functions later in code than themselves): %s" % self.stmt.func.attr)
            inargs, inargsize = pack_arguments(self.context.sigs['self'][self.stmt.func.attr],
                                                [parse_expr(arg, self.context) for arg in self.stmt.args],
                                                self.context)
            return LLLnode.from_list(['assert', ['call', ['gas'], ['address'], 0, inargs, inargsize, 0, 0]],
                                        typ=None, pos=getpos(self.stmt))
        elif isinstance(self.stmt.func, ast.Attribute) and isinstance(self.stmt.func.value, ast.Call):
            return external_contract_call_stmt(self.stmt, self.context)
        elif isinstance(self.stmt.func, ast.Attribute) and self.stmt.func.value.id == 'log':
            if self.stmt.func.attr not in self.context.sigs['self']:
                raise VariableDeclarationException("Event not declared yet: %s" % self.stmt.func.attr)
            event = self.context.sigs['self'][self.stmt.func.attr]
            topics_types, topics = [], []
            data_types, data = [], []
            for pos, is_indexed in enumerate(event.indexed_list):
                if is_indexed:
                    topics_types.append(event.args[pos].typ)
                    topics.append(self.stmt.args[pos])
                else:
                    data_types.append(event.args[pos].typ)
                    data.append(self.stmt.args[pos])
            topics, stored_topics = pack_logging_topics(event.event_id, topics, topics_types, self.context)
            inargs, inargsize, inarg_start = pack_logging_data(data_types, data, self.context)
            return LLLnode.from_list(['seq', inargs, stored_topics, ["log" + str(len(topics)), inarg_start, inargsize] + topics], typ=None, pos=getpos(self.stmt))
        else:
            raise StructureException("Unsupported operator: %r" % ast.dump(self.stmt), self.stmt)

    def parse_assert(self):
        from .parser import (
            parse_value_expr
        )
        return LLLnode.from_list(['assert', parse_value_expr(self.stmt.test, self.context)], typ=None, pos=getpos(self.stmt))

    def parse_for(self):
        from .parser import (
            parse_value_expr,
            parse_body,
        )
        if not isinstance(self.stmt.iter, ast.Call) or \
            not isinstance(self.stmt.iter.func, ast.Name) or \
                not isinstance(self.stmt.target, ast.Name) or \
                    self.stmt.iter.func.id != "range" or \
                        len(self.stmt.iter.args) not in (1, 2):
            raise StructureException("For statements must be of the form `for i in range(rounds): ..` or `for i in range(start, start + rounds): ..`", self.stmt.iter)
        # Type 1 for, eg. for i in range(10): ...
        if len(self.stmt.iter.args) == 1:
            if not isinstance(self.stmt.iter.args[0], ast.Num):
                raise StructureException("Repeat must have a nonzero positive integral number of rounds", self.stmt.iter)
            start = LLLnode.from_list(0, typ='num', pos=getpos(self.stmt))
            rounds = self.stmt.iter.args[0].n
        elif isinstance(self.stmt.iter.args[0], ast.Num) and isinstance(self.stmt.iter.args[1], ast.Num):
            # Type 2 for, eg. for i in range(100, 110): ...
            start = LLLnode.from_list(self.stmt.iter.args[0].n, typ='num', pos=getpos(self.stmt))
            rounds = LLLnode.from_list(self.stmt.iter.args[1].n - self.stmt.iter.args[0].n, typ='num', pos=getpos(self.stmt))
        else:
            # Type 3 for, eg. for i in range(x, x + 10): ...
            if not isinstance(self.stmt.iter.args[1], ast.BinOp) or not isinstance(self.stmt.iter.args[1].op, ast.Add):
                raise StructureException("Two-arg for statements must be of the form `for i in range(start, start + rounds): ...`",
                                            self.stmt.iter.args[1])
            if ast.dump(self.stmt.iter.args[0]) != ast.dump(self.stmt.iter.args[1].left):
                raise StructureException("Two-arg for statements of the form `for i in range(x, x + y): ...` must have x identical in both places: %r %r" % (ast.dump(self.stmt.iter.args[0]), ast.dump(self.stmt.iter.args[1].left)), self.stmt.iter)
            if not isinstance(self.stmt.iter.args[1].right, ast.Num):
                raise StructureException("Repeat must have a nonzero positive integral number of rounds", self.stmt.iter.args[1])
            start = parse_value_expr(self.stmt.iter.args[0], self.context)
            rounds = self.stmt.iter.args[1].right.n
        varname = self.stmt.target.id
        pos = self.context.vars[varname].pos if varname in self.context.forvars else self.context.new_variable(varname, BaseType('num'))
        o = LLLnode.from_list(['repeat', pos, start, rounds, parse_body(self.stmt.body, self.context)], typ=None, pos=getpos(self.stmt))
        self.context.forvars[varname] = True
        return o

    def aug_assign(self):
        from .parser import (
            parse_variable_location,
            parse_value_expr,
        )
        target = parse_variable_location(self.stmt.target, self.context)
        sub = parse_value_expr(self.stmt.value, self.context)
        if not isinstance(self.stmt.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod)):
            raise Exception("Unsupported operator for augassign")
        if not isinstance(target.typ, BaseType):
            raise TypeMismatchException("Can only use aug-assign operators with simple types!", self.stmt.target)
        if target.location == 'storage':
            if self.context.is_constant:
                raise ConstancyViolationException("Cannot modify storage inside a constant function!", self.stmt.target)
            o = parse_value_expr(ast.BinOp(left=LLLnode.from_list(['sload', '_stloc'], typ=target.typ, pos=target.pos),
                                    right=sub, op=self.stmt.op, lineno=self.stmt.lineno, col_offset=self.stmt.col_offset), self.context)
            return LLLnode.from_list(['with', '_stloc', target, ['sstore', '_stloc', base_type_conversion(o, o.typ, target.typ)]], typ=None, pos=getpos(self.stmt))
        elif target.location == 'memory':
            o = parse_value_expr(ast.BinOp(left=LLLnode.from_list(['mload', '_mloc'], typ=target.typ, pos=target.pos),
                                    right=sub, op=self.stmt.op, lineno=self.stmt.lineno, col_offset=self.stmt.col_offset), self.context)
            return LLLnode.from_list(['with', '_mloc', target, ['mstore', '_mloc', base_type_conversion(o, o.typ, target.typ)]], typ=None, pos=getpos(self.stmt))

    def parse_break(self):
        return LLLnode.from_list('break', typ=None, pos=getpos(self.stmt))

    def parse_return(self):
        from .parser import (
            parse_expr,
            make_setter
        )
        if self.context.return_type is None:
            if self.stmt.value:
                raise TypeMismatchException("Not expecting to return a value", self.stmt)
            return LLLnode.from_list(['return', 0, 0], typ=None, pos=getpos(self.stmt))
        if not self.stmt.value:
            raise TypeMismatchException("Expecting to return a value", self.stmt)
        sub = parse_expr(self.stmt.value, self.context)
        # Returning a value (most common case)
        if isinstance(sub.typ, BaseType):
            if not isinstance(self.context.return_type, BaseType):
                raise TypeMismatchException("Trying to return base type %r, output expecting %r" % (sub.typ, self.context.return_type), self.stmt.value)
            sub = unwrap_location(sub)
            if not are_units_compatible(sub.typ, self.context.return_type):
                raise TypeMismatchException("Return type units mismatch %r %r" % (sub.typ, self.context.return_type), self.stmt.value)
            elif is_base_type(sub.typ, self.context.return_type.typ) or \
                    (is_base_type(sub.typ, 'num') and is_base_type(self.context.return_type, 'signed256')):
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
            # Returning something already in memory
            if sub.location == 'memory':
                return LLLnode.from_list(['with', '_loc', sub,
                                            ['seq',
                                                ['mstore', ['sub', '_loc', 32], 32],
                                                ['return', ['sub', '_loc', 32], ['ceil32', ['add', ['mload', '_loc'], 64]]]]], typ=None, pos=getpos(self.stmt))
            # Copying from storage
            elif sub.location == 'storage':
                # Instantiate a byte array at some index
                fake_byte_array = LLLnode(self.context.get_next_mem() + 32, typ=sub.typ, location='memory', pos=getpos(self.stmt))
                o = ['seq',
                        # Copy the data to this byte array
                        make_byte_array_copier(fake_byte_array, sub),
                        # Store the number 32 before it for ABI formatting purposes
                        ['mstore', self.context.get_next_mem(), 32],
                        # Return it
                        ['return', self.context.get_next_mem(), ['add', ['ceil32', ['mload', self.context.get_next_mem() + 32]], 64]]]
                return LLLnode.from_list(o, typ=None, pos=getpos(self.stmt))
            else:
                raise Exception("Invalid location: %s" % sub.location)

        elif isinstance(sub.typ, ListType):
            if sub.location == "memory" and sub.value != "multi":
                return LLLnode.from_list(['return', sub, get_size_of_type(self.context.return_type) * 32],
                                            typ=None, pos=getpos(self.stmt))
            else:
                new_sub = LLLnode.from_list(self.context.new_placeholder(self.context.return_type), typ=self.context.return_type, location='memory')
                setter = make_setter(new_sub, sub, 'memory')
                return LLLnode.from_list(['seq', setter, ['return', new_sub, get_size_of_type(self.context.return_type) * 32]],
                                            typ=None, pos=getpos(self.stmt))

        # Returning a tuple.
        elif isinstance(sub.typ, TupleType):

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
                    dynamic_spot = LLLnode.from_list(['add', left_token, get_dynamic_offset_value()], location="memory", typ=arg.typ, annotation='dyanmic_spot')
                    subs.append(make_setter(dynamic_spot, arg, location="memory"))
                    subs.append(increment_dynamic_offset(dynamic_spot))

                elif isinstance(arg.typ, BaseType):
                    subs.append(make_setter(variable_offset, arg, "memory"))
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
