import ast as python_ast
import decimal
import sys
from typing import (
    Optional,
    Union,
)

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
    ast_struct: Union[dict, python_ast.AST],
    parent: Optional["VyperNode"] = None
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
            f"Invalid syntax (unsupported '{ast_struct['ast_type']}' Python AST node).",
            ast_struct['full_source_code'],
            ast_struct['lineno'],
            ast_struct['col_offset'],
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
        if isinstance(value, set):
            if node.get(key) not in value:
                return False
        elif node.get(key) != value:
            return False
    return True


def _sort_nodes(node_iterable):
    def sortkey(key):
        return float('inf') if key is None else key

    return sorted(
        node_iterable,
        key=lambda k: (sortkey(k.lineno), sortkey(k.col_offset), k.node_id),
    )


class VyperNode:
    """
    Base class for all vyper AST nodes.

    Vyper nodes are generated from, and closely resemble, their python counterparts.

    Object Attributes
    -----------------
    __slots__ : Tuple
        Allowed field names for the node.
    _description : str, optional
        A human-readable description of the node. Used to give more verbose error
        messages.
    _only_empty_fields : Tuple, optional
        Field names that, if present, must be set to None or a SyntaxException is
        raised. This attribute is used to exclude syntax that is valid in python
        but not in vyper.
    _translated_fields : Dict, optional
        Field names that should be reassigned if encountered. Used to normalize
        fields across different python versions.
    """
    __slots__ = BASE_NODE_ATTRIBUTES
    _only_empty_fields: tuple = ()
    _translated_fields: dict = {}

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
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
                    f"Syntax is valid Python but not valid for Vyper\n"
                    f"class: {type(self).__name__}, field_name: {field_name}",
                    kwargs['full_source_code'],
                    kwargs['lineno'],
                    kwargs['col_offset'],
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

    @property
    def description(self):
        return getattr(self, '_description', type(self).__name__)

    @classmethod
    def get_slots(cls) -> set:
        """
        Returns a set of field names for this node.
        """
        slot_fields = [x for i in cls.__mro__ for x in getattr(i, '__slots__', [])]
        return set(i for i in slot_fields if not i.startswith('_'))

    def to_dict(self) -> dict:
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

    def get_children(self, filters: Optional[dict] = None) -> list:
        """
        Returns direct childen of this node that match the given filter.

        Parameters
        ----------
        filters : dict, optional
            Dictionary of attribute names and expected values. Only nodes that
            contain the given attributes and match the given values are returned.
            * You can use dots within the name in order to check members of members.
              e.g. {'annotation.func.id': "constant"}
            * Expected values may be given as a set, in order to match a node must
              contain the given attribute and match any one value within the set.
              e.g. {'ast_type': {'BinOp', 'UnaryOp'}} will match both BinOp and
                   UnaryOp nodes.

        Returns
        -------
        list
            Child nodes matching the filter conditions, sorted by source offset.
        """
        children = _sort_nodes(self._children)
        if filters is None:
            return children
        return [i for i in children if _node_filter(i, filters)]

    def get_all_children(
        self, filters: Optional[dict] = None, include_self: Optional[bool] = False
    ) -> list:
        """
        Returns direct and indirect childen of this node that match the given filter.

        Parameters
        ----------
        filters : dict, optional
            Dictionary of attribute names and expected values. Only nodes that
            contain the given attributes and match the given values are returned.
            * You can use dots within the name in order to check members of members.
              e.g. {'annotation.func.id': "constant"}
            * Expected values may be given as a set, in order to match a node must
              contain the given attribute and match any one value within the set.
              e.g. {'ast_type': {'BinOp', 'UnaryOp'}} will match both BinOp and
                   UnaryOp nodes.
        include_self : bool, optional
            If True, this node is also included in the search results if it matches
            the given filter.

        Returns
        -------
        list
            Child nodes matching the filter conditions, sorted by source offset.
        """

        children = self.get_children(filters)
        for node in self.get_children():
            children.extend(node.get_all_children(filters))
        if include_self and _node_filter(self, filters):
            children.append(self)
        return _sort_nodes(children)

    def get(self, field_str: str) -> Optional["VyperNode"]:
        """
        Recursive getter function for node attributes.

        Parameters
        ----------
        field_str : str
            Attribute string of the location of the node to return.

        Returns
        -------
        VyperNode : optional
            Value at the location of the given field string, if one
            exists. Returns None if the field string is invalid.
        """
        obj = self
        for key in field_str.split("."):
            obj = getattr(obj, key, None)
        return obj


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
    __slots__ = ('args', 'body', 'returns', 'name', 'decorator_list', 'pos', 'doc_string')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if (
            kwargs.get('body') and
            isinstance(self.body[0], Expr) and
            isinstance(self.body[0].value, Str)
        ):
            # if the first body item is a docstring, move it into it's own field
            self.doc_string = self.body[0].value.s
            del self.body[0]


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

    @property
    def value(self):
        return self.s


class Str(Constant):
    __slots__ = ('s', )
    _translated_fields = {'value': 's'}

    @property
    def value(self):
        return self.s


class Num(Constant):
    # inherited class for all numeric constant node types
    __slots__ = ('n', )
    _translated_fields = {'value': 'n'}
    _python_ast_type = "Num"


class Int(Num):
    __slots__ = ()

    @property
    def value(self):
        return self.n


class Decimal(Num):
    __slots__ = ()

    @property
    def value(self):
        return decimal.Decimal(self.node_source_code)


class Hex(Num):
    __slots__ = ()

    @property
    def value(self):
        return self.node_source_code


class Binary(Num):
    __slots__ = ()

    @property
    def value(self):
        return self.node_source_code


class Octal(Num):
    __slots__ = ()

    @property
    def value(self):
        return self.node_source_code


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
    _description = "addition"


class Sub(VyperNode):
    __slots__ = ()
    _description = "subtraction"


class Mult(VyperNode):
    __slots__ = ()
    _description = "multiplication"


class Div(VyperNode):
    __slots__ = ()
    _description = "division"


class Mod(VyperNode):
    __slots__ = ()
    _description = "modulus"


class Pow(VyperNode):
    __slots__ = ()
    _description = "exponentiation"


class In(VyperNode):
    __slots__ = ()


class Gt(VyperNode):
    __slots__ = ()
    _description = "greater than"


class GtE(VyperNode):
    __slots__ = ()
    _description = "greater-or-equal"


class LtE(VyperNode):
    __slots__ = ()
    _description = "less-or-equal"


class Lt(VyperNode):
    __slots__ = ()
    _description = "less than"


class Eq(VyperNode):
    __slots__ = ()
    _description = "equality"


class NotEq(VyperNode):
    __slots__ = ()
    _description = "non-equality"


class And(VyperNode):
    __slots__ = ()


class Or(VyperNode):
    __slots__ = ()


class Not(VyperNode):
    __slots__ = ()


class USub(VyperNode):
    __slots__ = ()
    _description = "in-place subtraction"


class UAdd(VyperNode):
    __slots__ = ()
    _description = "in-place addition"


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
    _only_empty_fields = ('cause', )


class Slice(VyperNode):
    _only_empty_fields = ('lower', )


class alias(VyperNode):
    __slots__ = ('name', 'asname')


class ImportFrom(VyperNode):
    __slots__ = ('level', 'module', 'names')
