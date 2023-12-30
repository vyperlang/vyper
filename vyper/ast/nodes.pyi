import ast as python_ast
from typing import Any, Optional, Sequence, Type, Union

from .natspec import parse_natspec as parse_natspec
from .parse import parse_to_ast as parse_to_ast
from .parse import parse_to_ast_with_settings as parse_to_ast_with_settings
from .utils import ast_to_dict as ast_to_dict

NODE_BASE_ATTRIBUTES: Any
NODE_SRC_ATTRIBUTES: Any
DICT_AST_SKIPLIST: Any

def get_node(
    ast_struct: Union[dict, python_ast.AST], parent: Optional[VyperNode] = ...
) -> VyperNode: ...
def compare_nodes(left_node: VyperNode, right_node: VyperNode) -> bool: ...

class VyperNode:
    full_source_code: str = ...
    node_source_code: str = ...
    _metadata: dict = ...
    def __init__(self, parent: Optional[VyperNode] = ..., **kwargs: Any) -> None: ...
    def __hash__(self) -> Any: ...
    def __eq__(self, other: Any) -> Any: ...
    @property
    def description(self): ...
    @property
    def is_literal_value(self): ...
    @property
    def has_folded_value(self): ...
    @classmethod
    def get_fields(cls: Any) -> set: ...
    def get_folded_value(self) -> VyperNode: ...
    def _try_fold(self) -> VyperNode: ...
    @classmethod
    def from_node(cls, node: VyperNode, **kwargs: Any) -> Any: ...
    def to_dict(self) -> dict: ...
    def get_children(
        self,
        node_type: Union[Type[VyperNode], Sequence[Type[VyperNode]], None] = ...,
        filters: Optional[dict] = ...,
        reverse: bool = ...,
    ) -> Sequence: ...
    def get_descendants(
        self,
        node_type: Union[Type[VyperNode], Sequence[Type[VyperNode]], None] = ...,
        filters: Optional[dict] = ...,
        include_self: bool = ...,
        reverse: bool = ...,
    ) -> Sequence: ...
    def get_ancestor(
        self, node_type: Union[Type[VyperNode], Sequence[Type[VyperNode]], None] = ...
    ) -> VyperNode: ...
    def get(self, field_str: str) -> Any: ...

class TopLevel(VyperNode):
    doc_string: Str = ...
    body: list = ...
    name: str = ...
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...
    def __getitem__(self, key: Any) -> Any: ...
    def __iter__(self) -> Any: ...
    def __len__(self) -> int: ...
    def __contains__(self, obj: Any) -> bool: ...

class Module(TopLevel):
    path: str = ...
    resolved_path: str = ...
    def add_to_body(self, node: VyperNode) -> None: ...
    def remove_from_body(self, node: VyperNode) -> None: ...
    def namespace(self) -> Any: ...  # context manager

class FunctionDef(TopLevel):
    args: arguments = ...
    decorator_list: list = ...
    returns: VyperNode = ...

class arguments(VyperNode):
    args: list = ...
    defaults: list = ...

class arg(VyperNode): ...
class Return(VyperNode): ...

class Log(VyperNode):
    value: VyperNode = ...

class FlagDef(VyperNode):
    body: list = ...
    name: str = ...

class EventDef(VyperNode):
    body: list = ...
    name: str = ...

class InterfaceDef(VyperNode):
    body: list = ...
    name: str = ...

class StructDef(VyperNode):
    body: list = ...
    name: str = ...

class ExprNode(VyperNode): ...

class Constant(VyperNode):
    value: Any = ...

class Num(Constant):
    @property
    def n(self): ...

class Int(Num):
    value: int = ...

class Decimal(Num): ...

class Hex(Num):
    @property
    def n_bytes(self): ...

class Str(Constant):
    @property
    def s(self): ...

class Bytes(Constant):
    @property
    def s(self): ...

class NameConstant(Constant): ...
class Ellipsis(Constant): ...

class List(VyperNode):
    elements: list = ...

class Tuple(VyperNode):
    elements: list = ...

class Dict(VyperNode):
    keys: list = ...
    values: list = ...

class Name(VyperNode):
    id: str = ...
    _type: str = ...

class Expr(VyperNode):
    value: VyperNode = ...

class UnaryOp(ExprNode):
    op: VyperNode = ...
    operand: VyperNode = ...

class USub(VyperNode): ...
class Not(VyperNode): ...

class BinOp(ExprNode):
    left: VyperNode = ...
    op: VyperNode = ...
    right: VyperNode = ...

class Add(VyperNode): ...
class Sub(VyperNode): ...
class Mult(VyperNode): ...
class Div(VyperNode): ...
class Mod(VyperNode): ...
class Pow(VyperNode): ...
class LShift(VyperNode): ...
class RShift(VyperNode): ...
class BitAnd(VyperNode): ...
class BitOr(VyperNode): ...
class BitXor(VyperNode): ...

class BoolOp(ExprNode):
    op: VyperNode = ...
    values: list[VyperNode] = ...

class And(VyperNode): ...
class Or(VyperNode): ...

class Compare(ExprNode):
    op: VyperNode = ...
    left: VyperNode = ...
    right: VyperNode = ...

class Eq(VyperNode): ...
class NotEq(VyperNode): ...
class Lt(VyperNode): ...
class LtE(VyperNode): ...
class Gt(VyperNode): ...
class GtE(VyperNode): ...
class In(VyperNode): ...
class NotIn(VyperNode): ...

class Call(ExprNode):
    args: list = ...
    keywords: list = ...
    func: VyperNode = ...

class keyword(VyperNode): ...

class Attribute(VyperNode):
    attr: str = ...
    value: VyperNode = ...

class Subscript(VyperNode):
    slice: Index = ...
    value: VyperNode = ...

class Index(VyperNode):
    value: Constant = ...

class Assign(VyperNode): ...

class AnnAssign(VyperNode):
    target: Name = ...
    value: VyperNode = ...
    annotation: VyperNode = ...

class VariableDecl(VyperNode):
    target: Name = ...
    value: VyperNode = ...
    annotation: VyperNode = ...
    is_constant: bool = ...
    is_public: bool = ...
    is_immutable: bool = ...

class AugAssign(VyperNode):
    op: VyperNode = ...
    target: VyperNode = ...
    value: VyperNode = ...

class Raise(VyperNode): ...
class Assert(VyperNode): ...
class Pass(VyperNode): ...

class Import(VyperNode):
    alias: str = ...
    name: str = ...

class ImportFrom(VyperNode):
    alias: str = ...
    level: int = ...
    module: str = ...
    name: str = ...

class ImplementsDecl(VyperNode):
    target: Name = ...
    annotation: Name = ...

class If(VyperNode):
    body: list = ...
    orelse: list = ...

class IfExp(ExprNode):
    test: ExprNode = ...
    body: ExprNode = ...
    orelse: ExprNode = ...

class For(VyperNode): ...
class Break(VyperNode): ...
class Continue(VyperNode): ...
