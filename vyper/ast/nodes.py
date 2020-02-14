import ast as python_ast
import sys
import typing

from vyper.exceptions import (
    SyntaxException,
)
from vyper.settings import (
    VYPER_ERROR_CONTEXT_LINES,
    VYPER_ERROR_LINE_NUMBERS,
)
from vyper.utils import (
    annotate_source_code,
)

BASE_NODE_ATTRIBUTES = (
    '_children',
    '_enclosing_scope',
    '_parent',
    'ast_type',
    'col_offset',
    'end_col_offset',
    'end_lineno',
    'full_source_code',
    'lineno',
    'node_id',
    'node_source_code',
    'src',
)
DICT_AST_SKIPLIST = ('full_source_code', 'node_source_code')


def get_node(
    ast_struct: typing.Union[typing.Dict, python_ast.AST],
    parent: typing.Optional["VyperNode"] = None
) -> "VyperNode":
    """
    Converts an AST structure to a vyper AST node.

    This is a recursive call, all child nodes of the input value are also
    converted to vyper nodes.

    Attributes
    ----------
    ast_struct: (dict, AST)
        Annotated python AST node or vyper AST dict to generate the node from.
    parent: VyperNode, optional
        Parent node of the node being created.

    Returns
    -------
    VyperNode
        The generated AST object.
    """
    if not isinstance(ast_struct, dict):
        ast_struct = ast_struct.__dict__

    vy_class = getattr(sys.modules[__name__], ast_struct['ast_type'], None)

    if vy_class is None:
        raise SyntaxException(
            f"Invalid syntax (unsupported '{ast_struct['ast_type']}'' Python AST node).",
            ast_struct
        )

    return vy_class(parent=parent, **ast_struct)


def _to_node(value, parent):
    if isinstance(value, (dict, python_ast.AST)):
        return get_node(value, parent)
    return value


def _to_dict(value):
    if isinstance(value, VyperNode):
        return value.to_dict()
    return value


def _node_filter(node, filters):
    # recursive equality check for VyperNode.get_children filters
    for key, value in filters.items():
        obj = node
        for k in key.split("."):
            obj = getattr(obj, k, None)
        if obj != value:
            return False
    return True


class VyperNode:
    """
    Base class for all vyper AST nodes.

    Vyper nodes are generated from, and closely resemble, their python counterparts.

    Attributes
    ----------
    __slots__ : Tuple
        Allowed field names for the node.
    _only_empty_fields : Tuple
        Field names that, if present, must be set to None or a SyntaxException is
        raised. This attribute is used to exclude syntax that is valid in python
        but not in vyper.
    _translated_fields:
        Field names that should be reassigned if encountered. Used to normalize
        fields across different python versions.
    """
    __slots__ = BASE_NODE_ATTRIBUTES
    _only_empty_fields: typing.Tuple = ()
    _translated_fields: typing.Dict = {}

<<<<<<< HEAD
    def __init__(self, parent: typing.Optional["VyperNode"] = None, **kwargs: dict):
=======
    def __init__(self, parent: typing.Optional["VyperNode"] = None, **kwargs: typing.Dict):
>>>>>>> cbe2b30b... add enclosing_scope member to nodes
        """
        AST node initializer method.

        Node objects are not typically instantiated directly, you should instead
        create them using the get_node() method.

        Parameters
        ----------
        parent: VyperNode, optional
            Node which contains this node.
        **kwargs : dict
            Dictionary of fields to be included within the node.
        """
        self._parent = parent
        self._children: set = set()

        for field_name, value in kwargs.items():
            if field_name in self._translated_fields:
                field_name = self._translated_fields[field_name]

            if field_name in self.get_slots():
                if isinstance(value, list):
                    value = [_to_node(i, self) for i in value]
                else:
                    value = _to_node(value, self)
                setattr(self, field_name, value)

            elif value and field_name in self._only_empty_fields:
                raise SyntaxException(
                    f'Unsupported non-empty value (valid in Python, but invalid in Vyper) \n'
                    f' field_name: {field_name}, class: {type(self)} value: {value}'
                )

        # add to children of parent last to ensure an accurate hash is generated
        if parent is not None:
            parent._children.add(self)

    def __hash__(self):
        values = [getattr(self, i, None) for i in BASE_NODE_ATTRIBUTES if not i.startswith('_')]
        return hash(tuple(values))

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        for field_name in (i for i in self.get_slots() if i not in BASE_NODE_ATTRIBUTES):
            if getattr(self, field_name, None) != getattr(other, field_name, None):
                return False
        return True

    def __repr__(self):
        cls = type(self)
        class_repr = f'{cls.__module__}.{cls.__qualname__}'

        source_annotation = annotate_source_code(
            self.full_source_code,
            self.lineno,
            self.col_offset,
            context_lines=VYPER_ERROR_CONTEXT_LINES,
            line_numbers=VYPER_ERROR_LINE_NUMBERS,
        )

        return f'{class_repr}:\n{source_annotation}'

    @classmethod
    def get_slots(cls) -> typing.Set:
        """
        Returns a set of field names for this node.
        """
        slot_fields = [x for i in cls.__mro__ for x in getattr(i, '__slots__', [])]
        return set(i for i in slot_fields if not i.startswith('_'))

    def to_dict(self) -> typing.Dict:
        """
        Returns the node as a dict. All child nodes are also converted.
        """
        ast_dict = {}
        for key in [i for i in self.get_slots() if i not in DICT_AST_SKIPLIST]:
            value = getattr(self, key, None)
            if isinstance(value, list):
                ast_dict[key] = [_to_dict(i) for i in value]
            else:
                ast_dict[key] = _to_dict(value)
        return ast_dict

    @property
    def enclosing_scope(self) -> str:
        """
        The name of the enclosing scope for this node.

        If this node is contained within a function, the returned value is
        the name of that function. Otherwise, the returned value is "global".
        """
        node = self._parent
        while True:
            if node is None:
                return "global"
            if hasattr(node, '_enclosing_scope'):
                return node._enclosing_scope  # type: ignore
            node = node._parent

    def get_children(self, filters: typing.Optional[dict] = None) -> list:
        """
        Returns childen of this node that match the given filter.

        Parameters
        ----------
        filters : dict, optional
            Dictionary of attribute names and expected values. Only nodes that
            contain the given attributes and match the given values are returned.
            You can use dots within the name in order to check members of members,
            e.g. {'annotation.func.id': "constant"}

        Returns
        -------
        list
            Child nodes matching the filter conditions, sorted by source offset.
        """
        children = sorted(self._children, key=lambda k: (k.col_offset or 0, k.lineno or 0))
        if filters is None:
            return children
        return [i for i in children if _node_filter(i, filters)]


class Module(VyperNode):
    __slots__ = ('body', )

    def __getitem__(self, key):
        return self.body[key]

    def __iter__(self):
        return iter(self.body)

    def __len__(self):
        return len(self.body)

    def __contains__(self, obj):
        return obj in self.body


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

    def __init__(self, **kwargs):
        self._enclosing_scope = kwargs['name']
        super().__init__(**kwargs)


class arguments(VyperNode):
    __slots__ = ('args', 'defaults', 'default')
    _only_empty_fields = ('vararg', 'kwonlyargs', 'kwarg', 'kw_defaults')


class Import(VyperNode):
    __slots__ = ('names', )


class Call(VyperNode):
    __slots__ = ('func', 'args', 'keywords', 'keyword')


class keyword(VyperNode):
    __slots__ = ('arg', 'value')


class Compare(VyperNode):
    __slots__ = ('comparators', 'ops', 'left', 'right')


class Constant(VyperNode):
    # inherited class for all simple constant node types
    __slots__ = ()


class NameConstant(Constant):
    __slots__ = ('value', )


class Bytes(Constant):
    __slots__ = ('s', )
    _translated_fields = {'value': 's'}


class Str(Constant):
    __slots__ = ('s', )
    _translated_fields = {'value': 's'}


class Num(Constant):
    # inherited class for all numeric constant node types
    __slots__ = ('n', )
    _translated_fields = {'value': 'n'}
    _python_ast_type = "Num"


class Int(Num):
    __slots__ = ()


class Decimal(Num):
    __slots__ = ()


class Hex(Num):
    __slots__ = ()


class Binary(Num):
    __slots__ = ()


class Octal(Num):
    __slots__ = ()


class Attribute(VyperNode):
    __slots__ = ('attr', 'value',)


class Op(VyperNode):
    # inherited class for all operation node types
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


class UAdd(VyperNode):
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
    __slots__ = ('iter', 'target', 'body')
    _only_empty_fields = ('orelse', )


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
    _only_empty_fields = ('lower', )


class alias(VyperNode):
    __slots__ = ('name', 'asname')


class ImportFrom(VyperNode):
    __slots__ = ('level', 'module', 'names')
