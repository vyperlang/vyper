import ast as python_ast
import contextlib
import copy
import decimal
import functools
import math
import operator
import pickle
import sys
import warnings
from typing import Any, Optional, Union

from vyper.ast.metadata import NodeMetadata
from vyper.compiler.settings import VYPER_ERROR_CONTEXT_LINES, VYPER_ERROR_LINE_NUMBERS
from vyper.exceptions import (
    ArgumentException,
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    OverflowException,
    StructureException,
    SyntaxException,
    TypeMismatch,
    UnfoldableNode,
    VariableDeclarationException,
    VyperException,
    ZeroDivisionException,
)
from vyper.utils import (
    MAX_DECIMAL_PLACES,
    SizeLimits,
    annotate_source_code,
    evm_div,
    quantize,
    sha256sum,
)

NODE_BASE_ATTRIBUTES = (
    "_children",
    "_depth",
    "_parent",
    "ast_type",
    "node_id",
    "_metadata",
    "_original_node",
    "_cache_descendants",
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
    Convert an AST structure to a vyper AST node. Entry point to constructing
    vyper AST nodes.

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

        # workaround: some third party module (ex. ipython) might insert
        # a "parent" member into the node, creating a duplicate kwarg
        # error below when calling vy_class()
        if "parent" in ast_struct:
            ast_struct = copy.copy(ast_struct)
            del ast_struct["parent"]

    if ast_struct["ast_type"] == "AnnAssign" and isinstance(parent, Module):
        # Replace `implements` interface declarations `AnnAssign` with `ImplementsDecl`
        if getattr(ast_struct["target"], "id", None) == "implements":
            ast_struct["ast_type"] = "ImplementsDecl"

        # Replace "uses:" `AnnAssign` nodes with `UsesDecl`
        elif getattr(ast_struct["target"], "id", None) == "uses":
            ast_struct["ast_type"] = "UsesDecl"

        # Replace "initializes:" `AnnAssign` nodes with `InitializesDecl`
        elif getattr(ast_struct["target"], "id", None) == "initializes":
            ast_struct["ast_type"] = "InitializesDecl"

        # Replace "exports:" `AnnAssign` nodes with `ExportsDecl`
        elif getattr(ast_struct["target"], "id", None) == "exports":
            ast_struct["ast_type"] = "ExportsDecl"

        # Replace state and local variable declarations `AnnAssign` with `VariableDecl`
        else:
            ast_struct["ast_type"] = "VariableDecl"

    enum_warn = False
    if ast_struct["ast_type"] == "EnumDef":
        enum_warn = True
        ast_struct["ast_type"] = "FlagDef"

    vy_class = getattr(sys.modules[__name__], ast_struct["ast_type"], None)

    if vy_class is None:
        if ast_struct["ast_type"] == "Delete":
            _raise_syntax_exc("Deleting is not supported", ast_struct)
        elif ast_struct["ast_type"] in ("ExtSlice", "Slice"):
            _raise_syntax_exc("Vyper does not support slicing", ast_struct)
        elif ast_struct["ast_type"] == "UAdd":
            _raise_syntax_exc("Vyper does not support + as a unary operator", parent)
        else:
            _raise_syntax_exc(
                f"Invalid syntax (unsupported '{ast_struct['ast_type']}' Python AST node)",
                ast_struct,
            )

    node = vy_class(parent=parent, **ast_struct)

    # TODO: Putting this after node creation to pretty print, remove after enum deprecation
    if enum_warn:
        # TODO: hack to pretty print, logic should be factored out of exception
        pretty_printed_node = str(VyperException("", node))
        warnings.warn(
            f"enum will be deprecated in a future release, use flag instead. {pretty_printed_node}",
            stacklevel=2,
        )

    node.validate()

    return node


def _to_node(obj, parent):
    # if object is a Python node or dict representing a node, convert to a Vyper node
    if isinstance(obj, (dict, python_ast.AST)):
        return get_node(obj, parent)
    if isinstance(obj, VyperNode):
        # if object is already a vyper node, make sure the parent is set correctly
        # and fix any missing source offsets
        obj.set_parent(parent)
        for field_name in NODE_SRC_ATTRIBUTES:
            if getattr(obj, field_name) is None:
                setattr(obj, field_name, getattr(parent, field_name, None))
    return obj


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


def _apply_filters(node_iter, node_type, filters, reverse):
    ret = node_iter
    if node_type is not None:
        ret = (i for i in ret if isinstance(i, node_type))
    if filters is not None:
        ret = (i for i in ret if _node_filter(i, filters))

    ret = list(ret)
    if reverse:
        ret.reverse()
    return ret


def _raise_syntax_exc(error_msg: str, ast_struct: dict) -> None:
    # helper function to raise a SyntaxException from a dict representing a node
    raise SyntaxException(
        error_msg,
        ast_struct.get("full_source_code"),
        ast_struct.get("lineno"),
        ast_struct.get("col_offset"),
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
    _translated_fields : Dict, optional
        Field names that are reassigned if encountered. Used to normalize fields
        across different Python versions.
    """

    __slots__ = NODE_BASE_ATTRIBUTES + NODE_SRC_ATTRIBUTES

    _public_slots = [i for i in __slots__ if not i.startswith("_")]
    _only_empty_fields: tuple = ()
    _translated_fields: dict = {}

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
        # this function is performance-sensitive
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
        self.set_parent(parent)
        self._children: list = []
        self._metadata: NodeMetadata = NodeMetadata()
        self._original_node = None
        self._cache_descendants = None

        for field_name in NODE_SRC_ATTRIBUTES:
            # when a source offset is not available, use the parent's source offset
            value = kwargs.pop(field_name, None)
            if value is None:
                value = getattr(parent, field_name, None)
            setattr(self, field_name, value)

        for field_name, value in kwargs.items():
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
            parent._children.append(self)

    @property
    def parent(self):
        return self._parent

    # set parent, can be useful when inserting copied nodes into the AST
    def set_parent(self, parent: "VyperNode"):
        self._parent = parent
        self._depth = getattr(parent, "_depth", -1) + 1

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
        ast_struct = {i: getattr(node, i) for i in VyperNode._public_slots}
        ast_struct.update(ast_type=cls.__name__, **kwargs)
        return cls(**ast_struct)

    @classmethod
    @functools.lru_cache(maxsize=None)
    def get_fields(cls) -> set:
        """
        Return a set of field names for this node.

        Attributes that are prepended with an underscore are considered private
        and are not included within this sequence.
        """
        slot_fields = [x for i in cls.__mro__ for x in getattr(i, "__slots__", [])]
        return set(i for i in slot_fields if not i.startswith("_"))

    def __hash__(self):
        values = [getattr(self, i, None) for i in VyperNode._public_slots]
        return hash(tuple(values))

    def __deepcopy__(self, memo):
        # default implementation of deepcopy is a hotspot
        return pickle.loads(pickle.dumps(self))

    def __eq__(self, other):
        # CMC 2024-03-03 I'm not sure it makes much sense to compare AST
        # nodes, especially if they come from other modules
        if not isinstance(other, type(self)):
            return False
        if getattr(other, "node_id", None) != getattr(self, "node_id", None):
            return False
        for field_name in (i for i in self.get_fields() if i not in VyperNode.__slots__):
            if getattr(self, field_name, None) != getattr(other, field_name, None):
                return False
        return True

    def __repr__(self):
        cls = type(self)
        class_repr = f"{cls.__module__}.{cls.__qualname__}"
        return f"{class_repr}:\n{self._annotated_source}"

    @property
    def _annotated_source(self):
        # return source with context / line/col info
        return annotate_source_code(
            self.full_source_code,
            self.lineno,
            self.col_offset,
            context_lines=VYPER_ERROR_CONTEXT_LINES,
            line_numbers=VYPER_ERROR_LINE_NUMBERS,
        )

    @property
    def description(self):
        """
        Property method providing a human-readable description of a node.

        Node-specific description strings are added via the `_descrption` class
        attribute. If this attribute is not found, the name of the class is
        returned instead.
        """
        return getattr(self, "_description", type(self).__name__)

    @property
    def module_node(self):
        if isinstance(self, Module):
            return self
        return self.get_ancestor(Module)

    def get_id_dict(self):
        source_id = None
        if self.module_node is not None:
            source_id = self.module_node.source_id
        return {"node_id": self.node_id, "source_id": source_id}

    @property
    def is_literal_value(self):
        """
        Check if the node is a literal value.
        """
        return False

    @property
    def is_terminus(self):
        """
        Check if execution halts upon reaching this node.
        """
        return False

    @property
    def has_folded_value(self):
        """
        Property method to check if the node has a folded value.
        """
        return "folded_value" in self._metadata

    def get_folded_value(self) -> "ExprNode":
        """
        Attempt to get the folded value, bubbling up UnfoldableNode if the node
        is not foldable.
        """
        try:
            return self._metadata["folded_value"]
        except KeyError:
            raise UnfoldableNode("not foldable", self)

    def reduced(self) -> "ExprNode":
        if self.has_folded_value:
            return self.get_folded_value()
        return self

    def _set_folded_value(self, node: "VyperNode") -> None:
        # sanity check this is only called once
        assert "folded_value" not in self._metadata

        # set the "original node" so that exceptions can point to the original
        # node and not the folded node
        cls = node.__class__
        # make a fresh copy so that the node metadata is fresh.
        node = cls(**{i: getattr(node, i) for i in node.get_fields() if hasattr(node, i)})
        node._original_node = self

        self._metadata["folded_value"] = node

    def get_original_node(self) -> "VyperNode":
        return self._original_node or self

    def validate(self) -> None:
        """
        Validate the content of a node.

        Called by `ast.validation.validate_literal_nodes` to verify values
        within literal nodes.

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

        # TODO: add full analysis result, e.g. expr_info
        if "type" in self._metadata:
            ast_dict["type"] = self._metadata["type"].to_dict()

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
        return _apply_filters(iter(self._children), node_type, filters, reverse)

    def get_descendants(
        self,
        node_type: Union["VyperNode", tuple, None] = None,
        filters: Optional[dict] = None,
        include_self: bool = False,
        reverse: bool = False,
    ) -> list:
        # this function is performance-sensitive
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
        ret = self._get_descendants(include_self)
        return _apply_filters(ret, node_type, filters, reverse)

    def _get_descendants(self, include_self=True):
        # get descendants in topsort order
        if self._cache_descendants is None:
            ret = [self]
            for node in self._children:
                ret.extend(node._get_descendants())

            self._cache_descendants = ret

        ret = iter(self._cache_descendants)

        if not include_self:
            s = next(ret)  # pop
            assert s is self

        return ret

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


class Module(TopLevel):
    # metadata
    __slots__ = ("path", "resolved_path", "source_id")

    def to_dict(self):
        return dict(source_sha256sum=self.source_sha256sum, **super().to_dict())

    @property
    def source_sha256sum(self):
        return sha256sum(self.full_source_code)

    @contextlib.contextmanager
    def namespace(self):
        from vyper.semantics.namespace import get_namespace, override_global_namespace

        # kludge implementation for backwards compatibility.
        # TODO: replace with type_from_ast
        try:
            ns = self._metadata["namespace"]
        except AttributeError:
            ns = get_namespace()
        with override_global_namespace(ns):
            yield


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
    _only_empty_fields = ("posonlyargs", "vararg", "kwonlyargs", "kwarg", "kw_defaults")


class arg(VyperNode):
    __slots__ = ("arg", "annotation")


# base class for stmt nodes. doesn't do anything except classification
class Stmt(VyperNode):
    pass


class Return(Stmt):
    __slots__ = ("value",)

    @property
    def is_terminus(self):
        return True


class Expr(Stmt):
    __slots__ = ("value",)

    @property
    def is_terminus(self):
        return self.value.is_terminus


class NamedExpr(Stmt):
    __slots__ = ("target", "value")

    def validate(self):
        # module[dep1 := dep2]

        # XXX: better error messages
        if not isinstance(self.target, Name):
            raise StructureException("not a Name")

        if not isinstance(self.value, Name):
            raise StructureException("not a Name")


class Log(Stmt):
    __slots__ = ("value",)

    def validate(self):
        if not isinstance(self.value, Call):
            raise StructureException("Log must call an event", self.value)


class FlagDef(TopLevel):
    __slots__ = ("name", "body")


class EventDef(TopLevel):
    __slots__ = ("name", "body")


class InterfaceDef(TopLevel):
    __slots__ = ("name", "body")


class StructDef(TopLevel):
    __slots__ = ("name", "body")


# base class for expression nodes
# note that it is named ExprNode to avoid a conflict with
# the Expr type (which is a type of statement node, see python AST docs).
class ExprNode(VyperNode):
    __slots__ = ("_expr_info",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._expr_info = None

    def to_dict(self):
        ret = super().to_dict()
        if self._expr_info is None:
            return ret

        reads = [s.to_dict() for s in self._expr_info._reads]
        reads = [s for s in reads if s]
        if reads:
            ret["variable_reads"] = reads

        writes = [s.to_dict() for s in self._expr_info._writes]
        writes = [s for s in writes if s]
        if writes:
            ret["variable_writes"] = writes

        return ret


class Constant(ExprNode):
    # inherited class for all simple constant node types
    __slots__ = ("value",)

    @property
    def is_literal_value(self):
        return True


class Num(Constant):
    # inherited class for all numeric constant node types
    __slots__ = ()

    def validate(self):
        if self.value < SizeLimits.MIN_INT256:
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
        # note: maybe use self.value == quantize(self.value) for this check
        if self.value.as_tuple().exponent < -MAX_DECIMAL_PLACES:
            raise InvalidLiteral("Vyper supports a maximum of ten decimal points", self)
        if self.value < SizeLimits.MIN_AST_DECIMAL:
            raise OverflowException("Value is below lower bound for decimal types", self)
        if self.value > SizeLimits.MAX_AST_DECIMAL:
            raise OverflowException("Value exceeds upper bound for decimal types", self)


class Hex(Constant):
    """
    A hexadecimal value, e.g. `0xFF`

    Attributes
    ----------
    value : str
        Value of the node, represented as a string taken directly from the contract source.
    """

    __slots__ = ()

    def validate(self):
        if "_" in self.value:
            raise InvalidLiteral("Underscores not allowed in hex literals", self)
        if len(self.value) % 2:
            raise InvalidLiteral("Hex notation requires an even number of digits", self)

    @property
    def n_nibbles(self):
        """
        The number of nibbles this hex value represents
        """
        return len(self.value) - 2

    @property
    def n_bytes(self):
        """
        The number of bytes this hex value represents
        """
        return len(self.bytes_value)

    @property
    def bytes_value(self):
        """
        This value as bytes
        """
        return bytes.fromhex(self.value.removeprefix("0x"))


class Str(Constant):
    __slots__ = ()
    _translated_fields = {"s": "value"}

    def validate(self):
        for c in self.value:
            if ord(c) >= 256:
                raise InvalidLiteral(f"'{c}' is not an allowed string literal character", self)


class Bytes(Constant):
    __slots__ = ()
    _translated_fields = {"s": "value"}

    def __init__(self, parent: Optional["VyperNode"] = None, **kwargs: dict):
        super().__init__(parent, **kwargs)
        if isinstance(self.value, str):
            # convert hex string to bytes
            length = len(self.value) // 2 - 1
            self.value = int(self.value, 16).to_bytes(length, "big")

    def to_dict(self):
        ast_dict = super().to_dict()
        ast_dict["value"] = f"0x{self.value.hex()}"
        return ast_dict

    @property
    def s(self):
        return self.value


class List(ExprNode):
    __slots__ = ("elements",)
    _translated_fields = {"elts": "elements"}

    @property
    def is_literal_value(self):
        return all(e.is_literal_value for e in self.elements)


class Tuple(ExprNode):
    __slots__ = ("elements",)
    _translated_fields = {"elts": "elements"}

    @property
    def is_literal_value(self):
        return all(e.is_literal_value for e in self.elements)

    def validate(self):
        if not self.elements:
            raise InvalidLiteral("Cannot have an empty tuple", self)


class NameConstant(Constant):
    __slots__ = ()

    def validate(self):
        if self.value is None:
            raise InvalidLiteral("`None` is not a valid vyper value!", self)


class Ellipsis(Constant):
    __slots__ = ()


class Dict(ExprNode):
    __slots__ = ("keys", "values")

    @property
    def is_literal_value(self):
        return all(v.is_literal_value for v in self.values)


class Name(ExprNode):
    __slots__ = ("id",)


class UnaryOp(ExprNode):
    __slots__ = ("op", "operand")


class Operator(VyperNode):
    pass


class USub(Operator):
    __slots__ = ()
    _description = "negation"
    _op = operator.neg


class Not(Operator):
    __slots__ = ()
    _op = operator.not_


class Invert(Operator):
    __slots__ = ()
    _description = "bitwise not"
    _pretty = "~"

    def _op(self, value):
        return (2**256 - 1) ^ value


class BinOp(ExprNode):
    __slots__ = ("left", "op", "right")


class Add(Operator):
    __slots__ = ()
    _description = "addition"
    _pretty = "+"
    _op = operator.add


class Sub(Operator):
    __slots__ = ()
    _description = "subtraction"
    _pretty = "-"
    _op = operator.sub


class Mult(Operator):
    __slots__ = ()
    _description = "multiplication"
    _pretty = "*"

    def _op(self, left, right):
        assert type(left) is type(right)
        value = left * right
        if isinstance(left, decimal.Decimal):
            # ensure that the result is truncated to MAX_DECIMAL_PLACES
            try:
                # if the intermediate result requires too many decimal places,
                # decimal will puke - catch the error and raise an
                # OverflowException
                return quantize(value)
            except decimal.InvalidOperation:
                msg = f"{self._description} requires too many decimal places:"
                msg += f"\n  {left} * {right} => {value}"
                raise OverflowException(msg, self) from None
        else:
            return value


class Div(Operator):
    __slots__ = ()
    _description = "decimal division"
    _pretty = "/"

    def _op(self, left, right):
        # evaluate the operation using true division or floor division
        assert type(left) is type(right)
        if not right:
            raise ZeroDivisionException("Division by zero")

        if not isinstance(left, decimal.Decimal):
            raise UnfoldableNode("Cannot use `/` on non-decimals (did you mean `//`?)")

        value = left / right
        if value < 0:
            # the EVM always truncates toward zero
            value = -(-left / right)
        # ensure that the result is truncated to MAX_DECIMAL_PLACES
        try:
            return quantize(value)
        except decimal.InvalidOperation:
            msg = f"{self._description} requires too many decimal places:"
            msg += f"\n  {left} {self._pretty} {right} => {value}"
            raise OverflowException(msg, self) from None


class FloorDiv(VyperNode):
    __slots__ = ()
    _description = "integer division"
    _pretty = "//"

    def _op(self, left, right):
        # evaluate the operation using true division or floor division
        assert type(left) is type(right)
        if not right:
            raise ZeroDivisionException("Division by zero")

        if not isinstance(left, int):
            raise UnfoldableNode("Cannot use `//` on non-integers (did you mean `/`?)")

        return evm_div(left, right)


class Mod(Operator):
    __slots__ = ()
    _description = "modulus"
    _pretty = "%"

    def _op(self, left, right):
        if not right:
            raise ZeroDivisionException("Modulo by zero")

        value = abs(left) % abs(right)
        if left < 0:
            value = -value
        return value


class Pow(Operator):
    __slots__ = ()
    _description = "exponentiation"
    _pretty = "**"

    def _op(self, left, right):
        if isinstance(left, decimal.Decimal):
            raise TypeMismatch("Cannot perform exponentiation on decimal values.", self._parent)
        if right < 0:
            raise InvalidOperation("Cannot calculate a negative power", self._parent)
        # prevent a compiler hang. we are ok with false positives at this
        # stage since we are just trying to filter out inputs which can cause
        # the compiler to hang. the others will get caught during constant
        # folding or codegen.
        # l**r > 2**256
        # r * ln(l) > ln(2 ** 256)
        # r > ln(2 ** 256) / ln(l)
        if right > math.log(decimal.Decimal(2**257)) / math.log(decimal.Decimal(left)):
            raise InvalidLiteral("Out of bounds", self)

        return int(left**right)


class BitAnd(Operator):
    __slots__ = ()
    _description = "bitwise and"
    _pretty = "&"
    _op = operator.and_


class BitOr(Operator):
    __slots__ = ()
    _description = "bitwise or"
    _pretty = "|"
    _op = operator.or_


class BitXor(Operator):
    __slots__ = ()
    _description = "bitwise xor"
    _pretty = "^"
    _op = operator.xor


class LShift(Operator):
    __slots__ = ()
    _description = "bitwise left shift"
    _pretty = "<<"
    _op = operator.lshift


class RShift(Operator):
    __slots__ = ()
    _description = "bitwise right shift"
    _pretty = ">>"
    _op = operator.rshift


class BoolOp(ExprNode):
    __slots__ = ("op", "values")


class And(Operator):
    __slots__ = ()
    _description = "logical and"
    _op = all


class Or(Operator):
    __slots__ = ()
    _description = "logical or"
    _op = any


class Compare(ExprNode):
    """
    A comparison of two values.

    Attributes
    ----------
    left : ExprNode
        The left-hand value in the comparison.
    op : Operator
        The comparison operator.
    right : ExprNode
        The right-hand value in the comparison.
    """

    __slots__ = ("left", "op", "right")

    def __init__(self, *args, **kwargs):
        if len(kwargs["ops"]) > 1 or len(kwargs["comparators"]) > 1:
            _raise_syntax_exc("Cannot have a comparison with more than two elements", kwargs)

        kwargs["op"] = kwargs.pop("ops")[0]
        kwargs["right"] = kwargs.pop("comparators")[0]
        super().__init__(*args, **kwargs)


class Eq(Operator):
    __slots__ = ()
    _description = "equality"
    _op = operator.eq


class NotEq(Operator):
    __slots__ = ()
    _description = "non-equality"
    _op = operator.ne


class Lt(Operator):
    __slots__ = ()
    _description = "less than"
    _op = operator.lt


class LtE(Operator):
    __slots__ = ()
    _description = "less-or-equal"
    _op = operator.le


class Gt(Operator):
    __slots__ = ()
    _description = "greater than"
    _op = operator.gt


class GtE(Operator):
    __slots__ = ()
    _description = "greater-or-equal"
    _op = operator.ge


class In(Operator):
    __slots__ = ()
    _description = "membership"

    def _op(self, left, right):
        return left in right


class NotIn(Operator):
    __slots__ = ()
    _description = "exclusion"

    def _op(self, left, right):
        return left not in right


class Call(ExprNode):
    __slots__ = ("func", "args", "keywords")

    @property
    def is_extcall(self):
        return isinstance(self._parent, ExtCall)

    @property
    def is_staticcall(self):
        return isinstance(self._parent, StaticCall)

    @property
    def is_plain_call(self):
        return not (self.is_extcall or self.is_staticcall)

    @property
    def kind_str(self):
        if self.is_extcall:
            return "extcall"
        if self.is_staticcall:
            return "staticcall"
        raise CompilerPanic("unreachable!")  # pragma: nocover

    @property
    def is_terminus(self):
        # cursed import cycle!
        from vyper.builtins.functions import get_builtin_functions

        if not isinstance(self.func, Name):
            return False

        funcname = self.func.id
        builtin_t = get_builtin_functions().get(funcname)
        if builtin_t is None:
            return False

        return builtin_t._is_terminus


class ExtCall(ExprNode):
    __slots__ = ("value",)

    def validate(self):
        if not isinstance(self.value, Call):
            # TODO: investigate wrong col_offset for `self.value`
            raise StructureException(
                "`extcall` must be followed by a function call",
                self.value,
                hint="did you forget parentheses?",
            )


class StaticCall(ExprNode):
    __slots__ = ("value",)

    def validate(self):
        if not isinstance(self.value, Call):
            raise StructureException(
                "`staticcall` must be followed by a function call",
                self.value,
                hint="did you forget parentheses?",
            )


class keyword(VyperNode):
    __slots__ = ("arg", "value")


class Attribute(ExprNode):
    __slots__ = ("attr", "value")


class Subscript(ExprNode):
    __slots__ = ("slice", "value")


class Assign(Stmt):
    """
    An assignment.

    Attributes
    ----------
    target : VyperNode
        Left-hand side of the assignment.
    value : ExprNode
        Right-hand side of the assignment.
    """

    __slots__ = ("target", "value")

    def __init__(self, *args, **kwargs):
        if len(kwargs["targets"]) > 1:
            _raise_syntax_exc("Assignment statement must have one target", kwargs)

        kwargs["target"] = kwargs.pop("targets")[0]
        super().__init__(*args, **kwargs)


class AnnAssign(VyperNode):
    __slots__ = ("target", "annotation", "value")


class VariableDecl(VyperNode):
    """
    A contract variable declaration.

    Excludes `simple` attribute from Python `AnnAssign` node.

    Attributes
    ----------
    target : VyperNode
        Left-hand side of the assignment.
    value : VyperNode
        Right-hand side of the assignment.
    annotation : VyperNode
        Type of variable.
    is_constant : bool, optional
        If true, indicates that the variable is a constant variable.
    is_public : bool, optional
        If true, indicates that the variable is a public state variable.
    is_immutable : bool, optional
        If true, indicates that the variable is an immutable variable.
    """

    __slots__ = (
        "target",
        "annotation",
        "value",
        "is_constant",
        "is_public",
        "is_immutable",
        "is_transient",
        "_expanded_getter",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.is_constant = False
        self.is_public = False
        self.is_immutable = False
        self.is_transient = False
        self._expanded_getter = None

        def _check_args(annotation, call_name):
            # do the same thing as `validate_call_args`
            # (can't be imported due to cyclic dependency)
            if len(annotation.args) != 1:
                raise ArgumentException(f"Invalid number of arguments to `{call_name}`:", self)

        # the annotation is a "function" call, e.g.
        # `foo: public(constant(uint256))`
        # pretend we were parsing actual Vyper AST. annotation would be
        # TYPE | PUBLIC "(" TYPE | ((IMMUTABLE | CONSTANT) "(" TYPE ")") ")"
        if self.annotation.get("func.id") == "public":
            _check_args(self.annotation, "public")
            self.is_public = True
            # unwrap one layer
            self.annotation = self.annotation.args[0]

        func_id = self.annotation.get("func.id")
        if func_id in ("immutable", "constant", "transient"):
            _check_args(self.annotation, func_id)
            setattr(self, f"is_{func_id}", True)
            # unwrap one layer
            self.annotation = self.annotation.args[0]

        if isinstance(self.annotation, Call):
            _raise_syntax_exc("Invalid scope for variable declaration", self.annotation)

    @property
    def _pretty_location(self) -> str:
        if self.is_constant:
            return "Constant"
        if self.is_transient:
            return "Transient"
        if self.is_immutable:
            return "Immutable"
        return "Storage"

    def validate(self):
        if self.is_constant and self.value is None:
            raise VariableDeclarationException("Constant must be declared with a value", self)

        if not self.is_constant and self.value is not None:
            raise VariableDeclarationException(
                f"{self._pretty_location} variables cannot have an initial value", self.value
            )
        if not isinstance(self.target, Name):
            raise VariableDeclarationException("Invalid variable declaration", self.target)


class AugAssign(Stmt):
    __slots__ = ("op", "target", "value")


class Raise(Stmt):
    __slots__ = ("exc",)
    _only_empty_fields = ("cause",)

    @property
    def is_terminus(self):
        return True


class Assert(Stmt):
    __slots__ = ("test", "msg")


class Pass(Stmt):
    __slots__ = ()


class _ImportStmt(Stmt):
    __slots__ = ("name", "alias")

    def to_dict(self):
        ret = super().to_dict()
        if (import_info := self._metadata.get("import_info")) is not None:
            ret["import_info"] = import_info.to_dict()

        return ret

    def __init__(self, *args, **kwargs):
        if len(kwargs["names"]) > 1:
            _raise_syntax_exc("Assignment statement must have one target", kwargs)
        names = kwargs.pop("names")[0]
        kwargs["name"] = names.name
        kwargs["alias"] = names.asname
        super().__init__(*args, **kwargs)


class Import(_ImportStmt):
    __slots__ = ()


class ImportFrom(_ImportStmt):
    __slots__ = ("level", "module")


class ImplementsDecl(Stmt):
    """
    An `implements` declaration.

    Attributes
    ----------
    annotation : Name
        Name node for the interface to be implemented
    """

    __slots__ = ("annotation",)
    _only_empty_fields = ("value",)

    def validate(self):
        if not isinstance(self.annotation, (Name, Attribute)):
            raise StructureException("invalid implements", self.annotation)


def as_tuple(node: VyperNode):
    """
    Convenience function for some AST nodes which allow either a Tuple
    or single elements. Returns a python tuple of AST nodes.
    """
    if isinstance(node, Tuple):
        return node.elements
    else:
        return (node,)


class UsesDecl(Stmt):
    """
    A `uses` declaration.

    Attributes
    ----------
    annotation : Name | Attribute | Tuple
        The module(s) which this uses
    """

    __slots__ = ("annotation",)
    _only_empty_fields = ("value",)

    def validate(self):
        items = as_tuple(self.annotation)
        for item in items:
            if not isinstance(item, (Name, Attribute)):
                raise StructureException("invalid uses", item)


class InitializesDecl(Stmt):
    """
    An `initializes` declaration.

    Attributes
    ----------
    annotation : Name | Attribute | Subscript
        An imported module which this module initializes
    """

    __slots__ = ("annotation",)
    _only_empty_fields = ("value",)

    def validate(self):
        module_ref = self.annotation
        if isinstance(module_ref, Subscript):
            dependencies = as_tuple(module_ref.slice)
            module_ref = module_ref.value

            for item in dependencies:
                if not isinstance(item, NamedExpr):
                    raise StructureException(
                        "invalid dependency (hint: should be [dependency := dependency]", item
                    )
                if not isinstance(item.target, (Name, Attribute)):
                    raise StructureException("invalid module", item.target)
                if not isinstance(item.value, (Name, Attribute)):
                    raise StructureException("invalid module", item.target)

        if not isinstance(module_ref, (Name, Attribute)):
            raise StructureException("invalid module", module_ref)


class ExportsDecl(Stmt):
    """
    An `exports` declaration.

    Attributes
    ----------
    annotation : Name | Attribute | Tuple
        List of exports
    """

    __slots__ = ("annotation",)
    _only_empty_fields = ("value",)

    def validate(self):
        items = as_tuple(self.annotation)
        for item in items:
            if not isinstance(item, (Name, Attribute)):
                raise StructureException("invalid exports", item)


class If(Stmt):
    __slots__ = ("test", "body", "orelse")


class IfExp(ExprNode):
    __slots__ = ("test", "body", "orelse")


class For(Stmt):
    __slots__ = ("target", "iter", "body")
    _only_empty_fields = ("orelse",)


class Break(Stmt):
    __slots__ = ()


class Continue(Stmt):
    __slots__ = ()
