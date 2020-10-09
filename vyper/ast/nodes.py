import ast as python_ast
import decimal
import operator
import sys
from typing import Any, Optional, Union

from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    OverflowException,
    SyntaxException,
    TypeMismatch,
    UnfoldableNode,
    ZeroDivisionException,
)
from vyper.settings import VYPER_ERROR_CONTEXT_LINES, VYPER_ERROR_LINE_NUMBERS
from vyper.utils import MAX_DECIMAL_PLACES, SizeLimits, annotate_source_code

NODE_BASE_ATTRIBUTES = (
    "_children",
    "_depth",
    "_parent",
    "ast_type",
    "node_id",
)
NODE_SRC_ATTRIBUTES = (
    "col_offset",
    "end_col_offset",
    "end_lineno",
    "full_source_code",
    "lineno",
    "node_source_code",
    "src",
)

DICT_AST_SKIPLIST = ("full_source_code", "node_source_code")


def get_node(
    ast_struct: Union[dict, python_ast.AST], parent: Optional["VyperNode"] = None
) -> "VyperNode":
    """
    Convert an AST structure to a vyper AST node.

    This is a recursive call, all child nodes of the input value are also
    converted to Vyper nodes.

    Parameters
    ----------
    ast_struct: dict | AST
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

    vy_class = getattr(sys.modules[__name__], ast_struct["ast_type"], None)
    if not vy_class:
        if ast_struct["ast_type"] == "Delete":
            _raise_syntax_exc("Deleting is not supported", ast_struct)
        elif ast_struct["ast_type"] in ("ExtSlice", "Slice"):
            _raise_syntax_exc("Vyper does not support slicing", ast_struct)
        elif ast_struct["ast_type"] in ("Invert", "UAdd"):
            op = "+" if ast_struct["ast_type"] == "UAdd" else "~"
            _raise_syntax_exc(f"Vyper does not support {op} as a unary operator", parent)
        else:
            _raise_syntax_exc(
                f"Invalid syntax (unsupported '{ast_struct['ast_type']}' Python AST node)",
                ast_struct,
            )

    return vy_class(parent=parent, **ast_struct)


def compare_nodes(left_node: "VyperNode", right_node: "VyperNode") -> bool:
    """
    Compare the represented value(s) of two vyper nodes.

    This method evaluates a sort of "loose equality". It recursively compares the
    values of each field within two different nodes but does not compare the
    node_id or any members related to source offsets.

    Arguments
    ---------
    left_node : VyperNode
        First node object to compare.
    right_node : VyperNode
        Second node object to compare.

    Returns
    -------
    bool
        True if the given nodes represent the same value(s), False otherwise.
    """
    if not isinstance(left_node, type(right_node)):
        return False

    for field_name in (i for i in left_node.get_fields() if i not in VyperNode.__slots__):
        left_value = getattr(left_node, field_name, None)
        right_value = getattr(right_node, field_name, None)

        # compare types instead of isinstance() in case one node class inherits the other
        if type(left_value) is not type(right_value):
            return False

        if isinstance(left_value, list):
            if next((i for i in zip(left_value, right_value) if not compare_nodes(*i)), None):
                return False
        elif isinstance(left_value, VyperNode):
            if not compare_nodes(left_value, right_value):
                return False
        elif left_value != right_value:
            return False

    return True


def _to_node(value, parent):
    # if value is a Python node or dict representing a node, convert to a Vyper node
    if isinstance(value, (dict, python_ast.AST)):
        return get_node(value, parent)
    return value


def _to_dict(value):
    # if value is a Vyper node, convert to a dict
    if isinstance(value, VyperNode):
        return value.to_dict()
    return value


def _node_filter(node, filters):
    # recursive equality check for VyperNode.get_children filters
    if not filters:
        return True
    for key, value in filters.items():
        if isinstance(value, set):
            if node.get(key) not in value:
                return False
        elif node.get(key) != value:
            return False
    return True


def _sort_nodes(node_iterable):
    # sorting function for VyperNode.get_children

    def sortkey(key):
        return float("inf") if key is None else key

    return sorted(
        node_iterable, key=lambda k: (sortkey(k.lineno), sortkey(k.col_offset), k.node_id),
    )


def _raise_syntax_exc(error_msg: str, ast_struct: dict) -> None:
    # helper function to raise a SyntaxException from a dict representing a node
    raise SyntaxException(
        error_msg,
        ast_struct.get("full_source_code"),
        ast_struct.get("lineno"),
        ast_struct.get("col_offset"),
    )


def _validate_numeric_bounds(
    node: Union["BinOp", "UnaryOp"], value: Union[decimal.Decimal, int]
) -> None:
    if isinstance(value, decimal.Decimal):
        lower, upper = SizeLimits.MINNUM, SizeLimits.MAXNUM
    elif isinstance(value, int):
        lower, upper = SizeLimits.MINNUM, SizeLimits.MAX_UINT256
    else:
        raise CompilerPanic(f"Unexpected return type from {node._op}: {type(value)}")
    if not lower <= value <= upper:
        raise OverflowException(
            f"Result of {node.op.description} ({value}) is outside bounds of all numeric types",
            node,
        )


class VyperNode:
    """
    Base class for all vyper AST nodes.

    Vyper nodes are generated from, and closely resemble, their Python counterparts.
    Divergences are always handled in a node's `__init__` method, and explained
    in the node docstring.

    Class Attributes
    ----------------
    __slots__ : Tuple
        Allowed field names for the node.
    _description : str, optional
        A human-readable description of the node. Used to give more verbose error
        messages.
    _only_empty_fields : Tuple, optional
        Field names that, if present, must be set to None or a `SyntaxException`
        is raised. This attribute is used to exclude syntax that is valid in Python
        but not in Vyper.
    _terminus : bool, optional
        If `True`, indicates that execution halts upon reaching this node.
    _translated_fields : Dict, optional
        Field names that are reassigned if encountered. Used to normalize fields
        across different Python versions.
    """

    __slots__ = NODE_BASE_ATTRIBUTES + NODE_SRC_ATTRIBUTES
    _only_empty_fields: tuple = ()
    _translated_fields: dict = {}

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
        """
        AST node initializer method.

        Node objects are not typically instantiated directly, you should instead
        create them using the `get_node` method.

        Parameters
        ----------
        parent: VyperNode, optional
            Node which contains this node.
        **kwargs : dict
            Dictionary of fields to be included within the node.
        """
        self._parent = parent
        self._depth = getattr(parent, "_depth", -1) + 1
        self._children: set = set()

        for field_name in NODE_SRC_ATTRIBUTES:
            # when a source offset is not available, use the parent's source offset
            value = kwargs.get(field_name)
            if kwargs.get(field_name) is None:
                value = getattr(parent, field_name, None)
            setattr(self, field_name, value)

        for field_name, value in kwargs.items():
            if field_name in NODE_SRC_ATTRIBUTES:
                continue

            if field_name in self._translated_fields:
                field_name = self._translated_fields[field_name]

            if field_name in self.get_fields():
                if isinstance(value, list):
                    value = [_to_node(i, self) for i in value]
                else:
                    value = _to_node(value, self)
                setattr(self, field_name, value)

            elif value and field_name in self._only_empty_fields:
                _raise_syntax_exc(
                    f"Syntax is valid Python but not valid for Vyper\n"
                    f"class: {type(self).__name__}, field_name: {field_name}",
                    kwargs,
                )

        # add to children of parent last to ensure an accurate hash is generated
        if parent is not None:
            parent._children.add(self)

    @classmethod
    def from_node(cls, node: "VyperNode", **kwargs) -> "VyperNode":
        """
        Return a new VyperNode based on an existing node.

        This method creates a new node with the same source offsets as an existing
        node. The new node can then replace the existing node within the AST.
        Preserving source offsets ensures accurate error reporting and source
        map generation from the modified AST.

        Arguments
        ---------
        node: VyperNode
            An existing Vyper node. The generated node will have the same source
            offsets and ID as this node.
        **kwargs : Any
            Fields and values for the new node.

        Returns
        -------
        Vyper node instance
        """
        ast_struct = {i: getattr(node, i) for i in VyperNode.__slots__ if not i.startswith("_")}
        ast_struct.update(ast_type=cls.__name__, **kwargs)
        return cls(**ast_struct)

    @classmethod
    def get_fields(cls) -> set:
        """
        Return a set of field names for this node.

        Attributes that are prepended with an underscore are considered private
        and are not included within this sequence.
        """
        slot_fields = [x for i in cls.__mro__ for x in getattr(i, "__slots__", [])]
        return set(i for i in slot_fields if not i.startswith("_"))

    def __hash__(self):
        values = [getattr(self, i, None) for i in VyperNode.__slots__ if not i.startswith("_")]
        return hash(tuple(values))

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        if other.node_id != self.node_id:
            return False
        for field_name in (i for i in self.get_fields() if i not in VyperNode.__slots__):
            if getattr(self, field_name, None) != getattr(other, field_name, None):
                return False
        return True

    def __repr__(self):
        cls = type(self)
        class_repr = f"{cls.__module__}.{cls.__qualname__}"

        source_annotation = annotate_source_code(
            self.full_source_code,
            self.lineno,
            self.col_offset,
            context_lines=VYPER_ERROR_CONTEXT_LINES,
            line_numbers=VYPER_ERROR_LINE_NUMBERS,
        )

        return f"{class_repr}:\n{source_annotation}"

    @property
    def description(self):
        """
        Property method providing a human-readable description of a node.

        Node-specific description strings are added via the `_descrption` class
        attribute. If this attribute is not found, the name of the class is
        returned instead.
        """
        return getattr(self, "_description", type(self).__name__)

    def evaluate(self) -> "VyperNode":
        """
        Attempt to evaluate the content of a node and generate a new node from it.

        If a node cannot be evaluated it should raise `UnfoldableNode`. This base
        method acts as a catch-all to raise on any inherited classes that do not
        implement the method.
        """
        raise UnfoldableNode(f"{type(self)} cannot be evaluated")

    def validate(self) -> None:
        """
        Validate the content of a node.

        Called by `ast.validation.validate_literal_nodes` to verify values within
        literal nodes.

        Returns `None` if the node is valid, raises `InvalidLiteral` or another
        more expressive exception if the value cannot be valid within a Vyper
        contract.
        """
        pass

    def to_dict(self) -> dict:
        """
        Return the node as a dict. Child nodes and their descendants are also converted.
        """
        ast_dict = {}
        for key in [i for i in self.get_fields() if i not in DICT_AST_SKIPLIST]:
            value = getattr(self, key, None)
            if isinstance(value, list):
                ast_dict[key] = [_to_dict(i) for i in value]
            else:
                ast_dict[key] = _to_dict(value)
        return ast_dict

    def get_ancestor(self, node_type: Union["VyperNode", tuple, None] = None) -> "VyperNode":
        """
        Return an ancestor node for this node.

        An ancestor is any node which exists within the AST above the given node.

        Arguments
        ---------
        node_type : VyperNode | tuple, optional
            A node type or tuple of types. If given, this method checks all
            ancestor nodes of this node starting with the parent, and returns
            the first node with a type matching the given value.

        Returns
        -------
        With no arguments given: the parent of this node.

        With `node_type`: the first matching ascendant node, or `None` if no node
        is found which matches the argument value.
        """
        if node_type is None or self._parent is None:
            return self._parent

        if isinstance(self._parent, node_type):
            return self._parent

        return self._parent.get_ancestor(node_type)

    def get_children(
        self,
        node_type: Union["VyperNode", tuple, None] = None,
        filters: Optional[dict] = None,
        reverse: bool = False,
    ) -> list:
        """
        Return a list of children of this node which match the given filter(s).

        Results are sorted by the starting source offset and node ID, ascending.

        Parameters
        ----------
        node_type : VyperNode | tuple, optional
            A node type or tuple of types. If given, only child nodes where the
            type matches this value are returned. This is functionally identical
            to calling `isinstance(child, node_type)`
        filters : dict, optional
            Dictionary of attribute names and expected values. Only nodes that
            contain the given attributes and match the given values are returned.
            * You can use dots within the name in order to check members of members.
              e.g. `{'annotation.func.id': "constant"}`
            * Expected values may be given as a set, in order to match a node must
              contain the given attribute and match any one value within the set.
              e.g. `{'id': {'public', 'constant'}}` will match nodes with an `id`
                    member that contains either "public" or "constant".
        reverse : bool, optional
            If `True`, the order of results is reversed prior to return.

        Returns
        -------
        list
            Child nodes matching the filter conditions.
        """
        children = _sort_nodes(self._children)
        if node_type is not None:
            children = [i for i in children if isinstance(i, node_type)]
        if reverse:
            children.reverse()
        if filters is None:
            return children
        return [i for i in children if _node_filter(i, filters)]

    def get_descendants(
        self,
        node_type: Union["VyperNode", tuple, None] = None,
        filters: Optional[dict] = None,
        include_self: bool = False,
        reverse: bool = False,
    ) -> list:
        """
        Return a list of descendant nodes of this node which match the given filter(s).

        A descendant is any node which exists within the AST beneath the given node.

        Results are sorted by the starting source offset and depth, ascending. You
        can rely on that the sequence will always contain a parent node prior to any
        of it's children. If the result is reversed, all children of a node will
        be in the sequence prior to their parent.

        Parameters
        ----------
        node_type : VyperNode | tuple, optional
            A node type or tuple of types. If given, only child nodes where the
            type matches this value are returned. This is functionally identical
            to calling `isinstance(child, node_type)`
        filters : dict, optional
            Dictionary of attribute names and expected values. Only nodes that
            contain the given attributes and match the given values are returned.
            * You can use dots within the name in order to check members of members.
              e.g. `{'annotation.func.id': "constant"}`
            * Expected values may be given as a set, in order to match a node must
              contain the given attribute and match any one value within the set.
              e.g. `{'id': {'public', 'constant'}}` will match nodes with an `id`
                    member that contains either "public" or "constant".
        include_self : bool, optional
            If True, this node is also included in the search results if it matches
            the given filter.
        reverse : bool, optional
            If `True`, the order of results is reversed prior to return.

        Returns
        -------
        list
            Descendant nodes matching the filter conditions.
        """
        children = self.get_children(node_type, filters)
        for node in self.get_children():
            children.extend(node.get_descendants(node_type, filters))
        if (
            include_self
            and (not node_type or isinstance(self, node_type))
            and _node_filter(self, filters)
        ):
            children.append(self)
        result = _sort_nodes(children)
        if reverse:
            result.reverse()
        return result

    def get(self, field_str: str) -> Any:
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
            exists. `None` if the field string is empty or invalid.
        """
        obj = self
        for key in field_str.split("."):
            obj = getattr(obj, key, None)
        return obj


class TopLevel(VyperNode):
    """
    Inherited class for Module and FunctionDef nodes.

    Class attributes
    ----------------
    doc_string : Expr
        Expression node representing the docstring within this node.
    """

    __slots__ = ("body", "name", "doc_string")

    def __getitem__(self, key):
        return self.body[key]

    def __iter__(self):
        return iter(self.body)

    def __len__(self):
        return len(self.body)

    def __contains__(self, obj):
        return obj in self.body


class Module(TopLevel):
    __slots__ = ()

    def replace_in_tree(self, old_node: VyperNode, new_node: VyperNode) -> None:
        """
        Perform an in-place substitution of a node within the tree.

        Parameters
        ----------
        old_node : VyperNode
            Node object to be replaced. If the node does not currently exist
            within the AST, a `CompilerPanic` is raised.
        new_node : VyperNode
            Node object to replace new_node.

        Returns
        -------
        None
        """
        parent = old_node._parent
        if old_node not in self.get_descendants(type(old_node)):
            raise CompilerPanic("Node to be replaced does not exist within the tree")

        if old_node not in parent._children:
            raise CompilerPanic("Node to be replaced does not exist within parent children")

        is_replaced = False
        for key in parent.get_fields():
            obj = getattr(parent, key, None)
            if obj == old_node:
                if is_replaced:
                    raise CompilerPanic("Node to be replaced exists as multiple members in parent")
                setattr(parent, key, new_node)
                is_replaced = True
            elif isinstance(obj, list) and obj.count(old_node):
                if is_replaced or obj.count(old_node) > 1:
                    raise CompilerPanic("Node to be replaced exists as multiple members in parent")
                obj[obj.index(old_node)] = new_node
                is_replaced = True
        if not is_replaced:
            raise CompilerPanic("Node to be replaced does not exist within parent members")

        parent._children.remove(old_node)

        new_node._parent = parent
        new_node._depth = old_node._depth
        parent._children.add(new_node)


class FunctionDef(TopLevel):
    __slots__ = ("args", "returns", "decorator_list", "pos")


class DocStr(VyperNode):
    """
    A docstring.

    Attributes
    ----------
    value : str
        Value of the node, represented as an string.
    """

    __slots__ = ("value",)
    _translated_fields = {"s": "value"}


class arguments(VyperNode):
    __slots__ = ("args", "defaults", "default")
    _only_empty_fields = ("vararg", "kwonlyargs", "kwarg", "kw_defaults")


class arg(VyperNode):
    __slots__ = ("arg", "annotation")


class Return(VyperNode):
    __slots__ = ("value",)
    _is_terminus = True


class Log(VyperNode):
    __slots__ = ("value",)


class EventDef(VyperNode):
    __slots__ = ("name", "body")


class InterfaceDef(VyperNode):
    __slots__ = ("name", "body")


class StructDef(VyperNode):
    __slots__ = ("name", "body")


class Constant(VyperNode):
    # inherited class for all simple constant node types
    __slots__ = ("value",)


class Num(Constant):
    # inherited class for all numeric constant node types
    __slots__ = ()
    _translated_fields = {"n": "value"}

    @property
    def n(self):
        # TODO phase out use of Num.n and remove this
        return self.value

    def validate(self):
        if self.value < SizeLimits.MINNUM:
            raise OverflowException("Value is below lower bound for all numeric types", self)
        if self.value > SizeLimits.MAX_UINT256:
            raise OverflowException("Value exceeds upper bound for all numeric types", self)


class Int(Num):
    """
    An integer.

    Attributes
    ----------
    value : int
        Value of the node, represented as an integer.
    """

    __slots__ = ()


class Decimal(Num):
    """
    A decimal.

    Attributes
    ----------
    value : decimal.Decimal
        Value of the node, represented as a Decimal object.
    """

    __slots__ = ()

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
        super().__init__(parent, **kwargs)
        if not isinstance(self.value, decimal.Decimal):
            self.value = decimal.Decimal(self.value)

    def to_dict(self):
        ast_dict = super().to_dict()
        ast_dict["value"] = self.node_source_code
        return ast_dict

    def validate(self):
        if self.value.as_tuple().exponent < -MAX_DECIMAL_PLACES:
            raise InvalidLiteral("Vyper supports a maximum of ten decimal points", self)
        super().validate()


class Hex(Num):
    """
    A hexadecimal value, e.g. `0xFF`

    Attributes
    ----------
    value : str
        Value of the node, represented as a string taken directly from the contract source.
    """

    __slots__ = ()

    def validate(self):
        if len(self.value) % 2:
            raise InvalidLiteral("Hex notation requires an even number of digits", self)


class Str(Constant):
    __slots__ = ()
    _translated_fields = {"s": "value"}

    def validate(self):
        for c in self.value:
            if ord(c) >= 256:
                raise InvalidLiteral(f"'{c}' is not an allowed string literal character", self)

    @property
    def s(self):
        # TODO phase out use of Str.s and remove this
        return self.value


class Bytes(Constant):
    __slots__ = ()
    _translated_fields = {"s": "value"}

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
        super().__init__(parent, **kwargs)
        if isinstance(self.value, str):
            self.value = self.value.encode("utf8")

    def to_dict(self):
        ast_dict = super().to_dict()
        ast_dict["value"] = self.value.decode("utf8")
        return ast_dict

    @property
    def s(self):
        return self.value


class List(VyperNode):
    __slots__ = ("elements",)
    _translated_fields = {"elts": "elements"}


class Tuple(VyperNode):
    __slots__ = ("elements",)
    _translated_fields = {"elts": "elements"}

    def validate(self):
        if not self.elements:
            raise InvalidLiteral("Cannot have an empty tuple", self)


class Dict(VyperNode):
    __slots__ = ("keys", "values")


class NameConstant(Constant):
    __slots__ = ("value",)


class Name(VyperNode):
    __slots__ = (
        "id",
        "_type",
    )


class Expr(VyperNode):
    __slots__ = ("value",)


class UnaryOp(VyperNode):
    __slots__ = (
        "op",
        "operand",
    )

    def evaluate(self) -> VyperNode:
        """
        Attempt to evaluate the unary operation.

        Returns
        -------
        Int | Decimal
            Node representing the result of the evaluation.
        """
        if isinstance(self.op, Not) and not isinstance(self.operand, NameConstant):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")
        if isinstance(self.op, USub) and not isinstance(self.operand, (Int, Decimal)):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        value = self.op._op(self.operand.value)
        _validate_numeric_bounds(self, value)
        return type(self.operand).from_node(self, value=value)


class USub(VyperNode):
    __slots__ = ()
    _description = "negation"
    _op = operator.neg


class Not(VyperNode):
    __slots__ = ()
    _op = operator.not_


class BinOp(VyperNode):
    __slots__ = (
        "left",
        "op",
        "right",
    )

    def evaluate(self) -> VyperNode:
        """
        Attempt to evaluate the arithmetic operation.

        Returns
        -------
        Int | Decimal
            Node representing the result of the evaluation.
        """
        left, right = self.left, self.right
        if type(left) is not type(right):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")
        if not isinstance(left, (Int, Decimal)):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        value = self.op._op(left.value, right.value)
        _validate_numeric_bounds(self, value)
        return type(left).from_node(self, value=value)


class Add(VyperNode):
    __slots__ = ()
    _description = "addition"
    _op = operator.add


class Sub(VyperNode):
    __slots__ = ()
    _description = "subtraction"
    _op = operator.sub


class Mult(VyperNode):
    __slots__ = ()
    _description = "multiplication"

    def _op(self, left, right):
        assert type(left) is type(right)
        value = left * right
        if isinstance(left, decimal.Decimal):
            # ensure that the result is truncated to MAX_DECIMAL_PLACES
            return value.quantize(
                decimal.Decimal(f"{1:0.{MAX_DECIMAL_PLACES}f}"), decimal.ROUND_DOWN
            )
        else:
            return value


class Div(VyperNode):
    __slots__ = ()
    _description = "division"

    def _op(self, left, right):
        # evaluate the operation using true division or floor division
        assert type(left) is type(right)
        if not right:
            raise ZeroDivisionException("Division by zero")

        if isinstance(left, decimal.Decimal):
            value = left / right
            if value < 0:
                # the EVM always truncates toward zero
                value = -(-left / right)
            # ensure that the result is truncated to MAX_DECIMAL_PLACES
            return value.quantize(
                decimal.Decimal(f"{1:0.{MAX_DECIMAL_PLACES}f}"), decimal.ROUND_DOWN
            )
        else:
            value = left // right
            if value < 0:
                return -(-left // right)
            return value


class Mod(VyperNode):
    __slots__ = ()
    _description = "modulus"

    def _op(self, left, right):
        if not right:
            raise ZeroDivisionException("Modulo by zero")

        value = abs(left) % abs(right)
        if left < 0:
            value = -value
        return value


class Pow(VyperNode):
    __slots__ = ()
    _description = "exponentiation"

    def _op(self, left, right):
        if isinstance(left, decimal.Decimal):
            raise TypeMismatch("Cannot perform exponentiation on decimal values.", self._parent)
        if right < 0:
            raise InvalidOperation("Cannot calculate a negative power", self._parent)
        return int(left ** right)


class BoolOp(VyperNode):
    __slots__ = (
        "op",
        "values",
    )

    def evaluate(self) -> VyperNode:
        """
        Attempt to evaluate the boolean operation.

        Returns
        -------
        NameConstant
            Node representing the result of the evaluation.
        """
        if next((i for i in self.values if not isinstance(i, NameConstant)), None):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        values = [i.value for i in self.values]
        if None in values:
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        value = self.op._op(values)
        return NameConstant.from_node(self, value=value)


class And(VyperNode):
    __slots__ = ()
    _description = "greater-or-equal"
    _op = all


class Or(VyperNode):
    __slots__ = ()
    _description = "less-or-equal"
    _op = any


class Compare(VyperNode):
    """
    A comparison of two values.

    Attributes
    ----------
    left : VyperNode
        The left-hand value in the comparison.
    op : VyperNode
        The comparison operator.
    right : VyperNode
        The right-hand value in the comparison.
    """

    __slots__ = ("left", "op", "right")

    def __init__(self, *args, **kwargs):
        if len(kwargs["ops"]) > 1 or len(kwargs["comparators"]) > 1:
            _raise_syntax_exc("Cannot have a comparison with more than two elements", kwargs)

        kwargs["op"] = kwargs.pop("ops")[0]
        kwargs["right"] = kwargs.pop("comparators")[0]
        super().__init__(*args, **kwargs)

    def evaluate(self) -> VyperNode:
        """
        Attempt to evaluate the comparison.

        Returns
        -------
        NameConstant
            Node representing the result of the evaluation.
        """
        left, right = self.left, self.right
        if not isinstance(left, Constant):
            raise UnfoldableNode("Node contains invalid field(s) for evaluation")

        if isinstance(self.op, In):
            if not isinstance(right, List):
                raise UnfoldableNode("Node contains invalid field(s) for evaluation")
            if next((i for i in right.elements if not isinstance(i, Constant)), None):
                raise UnfoldableNode("Node contains invalid field(s) for evaluation")
            if len(set([type(i) for i in right.elements])) > 1:
                raise UnfoldableNode("List contains multiple literal types")
            value = self.op._op(left.value, [i.value for i in right.elements])
            return NameConstant.from_node(self, value=value)

        if not isinstance(left, type(right)):
            raise UnfoldableNode("Cannot compare different literal types")

        if not isinstance(self.op, (Eq, NotEq)) and not isinstance(left, (Int, Decimal)):
            raise TypeMismatch(f"Invalid literal types for {self.op.description} comparison", self)

        value = self.op._op(left.value, right.value)
        return NameConstant.from_node(self, value=value)


class Eq(VyperNode):
    __slots__ = ()
    _description = "equality"
    _op = operator.eq


class NotEq(VyperNode):
    __slots__ = ()
    _description = "non-equality"
    _op = operator.ne


class Lt(VyperNode):
    __slots__ = ()
    _description = "less than"
    _op = operator.lt


class LtE(VyperNode):
    __slots__ = ()
    _description = "less-or-equal"
    _op = operator.le


class Gt(VyperNode):
    __slots__ = ()
    _description = "greater than"
    _op = operator.gt


class GtE(VyperNode):
    __slots__ = ()
    _description = "greater-or-equal"
    _op = operator.ge


class In(VyperNode):
    __slots__ = ()
    _description = "membership"

    def _op(self, left, right):
        return left in right


class Call(VyperNode):
    __slots__ = ("func", "args", "keywords", "keyword")


class keyword(VyperNode):
    __slots__ = ("arg", "value")


class Attribute(VyperNode):
    __slots__ = (
        "attr",
        "value",
    )


class Subscript(VyperNode):
    __slots__ = ("slice", "value")

    def evaluate(self) -> VyperNode:
        """
        Attempt to evaluate the subscript.

        This method reduces an indexed reference to a literal array into the value
        within the array, e.g. `["foo", "bar"][1]` becomes `"bar"`

        Returns
        -------
        VyperNode
            Node representing the result of the evaluation.
        """
        if not isinstance(self.value, List):
            raise UnfoldableNode("Subscript object is not a literal list")
        elements = self.value.elements
        if len(set([type(i) for i in elements])) > 1:
            raise UnfoldableNode("List contains multiple node types")
        idx = self.slice.get("value.value")
        if not isinstance(idx, int) or idx < 0 or idx >= len(elements):
            raise UnfoldableNode("Invalid index value")

        return elements[idx]


class Index(VyperNode):
    __slots__ = ("value",)


class Assign(VyperNode):
    """
    An assignment.

    Attributes
    ----------
    target : VyperNode
        Left-hand side of the assignment.
    value : VyperNode
        Right-hand side of the assignment.
    """

    __slots__ = ("target", "value")

    def __init__(self, *args, **kwargs):
        if len(kwargs["targets"]) > 1:
            _raise_syntax_exc("Assignment statement must have one target", kwargs)

        kwargs["target"] = kwargs.pop("targets")[0]
        super().__init__(*args, **kwargs)


class AnnAssign(VyperNode):
    __slots__ = ("target", "annotation", "value", "simple")


class AugAssign(VyperNode):
    __slots__ = ("op", "target", "value")


class Raise(VyperNode):
    __slots__ = ("exc",)
    _only_empty_fields = ("cause",)
    _is_terminus = True


class Assert(VyperNode):
    __slots__ = ("test", "msg")


class Pass(VyperNode):
    __slots__ = ()


class _Import(VyperNode):
    __slots__ = ("name", "alias")

    def __init__(self, *args, **kwargs):
        if len(kwargs["names"]) > 1:
            _raise_syntax_exc("Assignment statement must have one target", kwargs)
        names = kwargs.pop("names")[0]
        kwargs["name"] = names.name
        kwargs["alias"] = names.asname
        super().__init__(*args, **kwargs)


class Import(_Import):
    __slots__ = ()


class ImportFrom(_Import):
    __slots__ = ("level", "module")


class If(VyperNode):
    __slots__ = ("test", "body", "orelse")


class For(VyperNode):
    __slots__ = ("iter", "target", "body")
    _only_empty_fields = ("orelse",)


class Break(VyperNode):
    __slots__ = ()


class Continue(VyperNode):
    __slots__ = ()
