from itertools import (
    chain,
)
import typing

from vyper.exceptions import (
    CompilerPanic,
)

BASE_NODE_ATTRIBUTES = ('node_id', 'source_code', 'col_offset', 'lineno')


class VyperNode:
    __slots__ = BASE_NODE_ATTRIBUTES
    ignored_fields: typing.Tuple = ('ctx', )
    only_empty_fields: typing.Tuple = ()

    @classmethod
    def get_slots(cls):
        return set(chain.from_iterable(
            getattr(klass, '__slots__', [])
            for klass in cls.__class__.mro(cls)
        ))

    def __init__(self, **kwargs):

        for field_name, value in kwargs.items():
            if field_name in self.get_slots():
                setattr(self, field_name, value)
            elif value:
                raise CompilerPanic(
                    f'Unsupported non-empty value field_name: {field_name}, '
                    f' class: {type(self)} value: {value}'
                )

    def __eq__(self, other):
        if isinstance(other, type(self)):
            for field_name in self.get_slots():
                if field_name not in ('node_id', 'source_code', 'col_offset', 'lineno'):
                    if getattr(self, field_name, None) != getattr(other, field_name, None):
                        return False
            return True
        else:
            return False


class Module(VyperNode):
    __slots__ = ('body', )


class Name(VyperNode):
    __slots__ = ('id', )


class Subscript(VyperNode):
    __slots__ = ('slice', 'value')


class Index(VyperNode):
    __slots__ = ('value', )


class arg(VyperNode):
    __slots__ = ('arg', 'annotation')


class Tuple(VyperNode):
    __slots__ = ('elts', )


class FunctionDef(VyperNode):
    __slots__ = ('args', 'body', 'returns', 'name', 'decorator_list', 'pos')


class arguments(VyperNode):
    __slots__ = ('args', 'defaults', 'default')
    only_empty_fields = ('vararg', 'kwonlyargs', 'kwarg', 'kw_defaults')


class Import(VyperNode):
    __slots__ = ('names', )


class Call(VyperNode):
    __slots__ = ('func', 'args', 'keywords', 'keyword')


class keyword(VyperNode):
    __slots__ = ('arg', 'value')


class Str(VyperNode):
    __slots__ = ('s', )


class Compare(VyperNode):
    __slots__ = ('comparators', 'ops', 'left', 'right')


class Num(VyperNode):
    __slots__ = ('n', )


class NameConstant(VyperNode):
    __slots__ = ('value', )


class Attribute(VyperNode):
    __slots__ = ('attr', 'value',)


class Op(VyperNode):
    __slots__ = ('op', 'left', 'right')


class BoolOp(Op):
    __slots__ = ('values', )


class BinOp(Op):
    __slots__ = ()


class UnaryOp(Op):
    __slots__ = ('operand', )


class List(VyperNode):
    __slots__ = ('elts', )


class Dict(VyperNode):
    __slots__ = ('keys', 'values')


class Bytes(VyperNode):
    __slots__ = ('s', )


class Add(VyperNode):
    __slots__ = ()


class Sub(VyperNode):
    __slots__ = ()


class Mult(VyperNode):
    __slots__ = ()


class Div(VyperNode):
    __slots__ = ()


class Mod(VyperNode):
    __slots__ = ()


class Pow(VyperNode):
    __slots__ = ()


class In(VyperNode):
    __slots__ = ()


class Gt(VyperNode):
    __slots__ = ()


class GtE(VyperNode):
    __slots__ = ()


class LtE(VyperNode):
    __slots__ = ()


class Lt(VyperNode):
    __slots__ = ()


class Eq(VyperNode):
    __slots__ = ()


class NotEq(VyperNode):
    __slots__ = ()


class And(VyperNode):
    __slots__ = ()


class Or(VyperNode):
    __slots__ = ()


class Not(VyperNode):
    __slots__ = ()


class USub(VyperNode):
    __slots__ = ()


class Expr(VyperNode):
    __slots__ = ('value', )


class Pass(VyperNode):
    __slots__ = ()


class AnnAssign(VyperNode):
    __slots__ = ('target', 'annotation', 'value', 'simple')


class Assign(VyperNode):
    __slots__ = ('targets', 'value')


class If(VyperNode):
    __slots__ = ('test', 'body', 'orelse')


class Assert(VyperNode):
    __slots__ = ('test', 'msg')


class For(VyperNode):
    __slots__ = ('iter', 'target', 'orelse', 'body')


class AugAssign(VyperNode):
    __slots__ = ('op', 'target', 'value')


class Break(VyperNode):
    __slots__ = ()


class Continue(VyperNode):
    __slots__ = ()


class Return(VyperNode):
    __slots__ = ('value', )


class Delete(VyperNode):
    __slots__ = ('targets', )


class stmt(VyperNode):
    __slots__ = ()


class ClassDef(VyperNode):
    __slots__ = ('class_type', 'name', 'body')


class Raise(VyperNode):
    __slots__ = ('exc', )


class Slice(VyperNode):
    only_empty_fields = ('lower', )


class alias(VyperNode):
    __slots__ = ('name', 'asname')


class ImportFrom(VyperNode):
    __slots__ = ('module', 'names')
