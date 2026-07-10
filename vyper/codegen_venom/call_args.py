"""Reusable call-boundary argument policies and prepared representations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional, Union

from vyper import ast as vy_ast
from vyper.codegen_venom.value import PreparedValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import AddressT, VyperType
from vyper.venom.basicblock import IROperand


class DataViewKind(Enum):
    CALLDATA = auto()
    SELF_CODE = auto()
    EXTERNAL_CODE = auto()


@dataclass(frozen=True)
class DataView:
    """A raw data source which must be consumed by an authorized handler."""

    kind: DataViewKind
    address: Optional[PreparedValue] = None

    def __post_init__(self):
        has_address = self.address is not None
        if has_address != (self.kind is DataViewKind.EXTERNAL_CODE):  # pragma: nocover
            raise CompilerPanic("external code views require exactly one address")

    def address_operand(self) -> IROperand:
        if self.address is None:  # pragma: nocover
            raise CompilerPanic(f"{self.kind.name.lower()} view has no address")
        return self.address.word()


@dataclass(frozen=True)
class PreparedList:
    """A fixed-shape list whose runtime elements were prepared in source order."""

    values: tuple[PreparedValue, ...]


@dataclass(frozen=True)
class TypeArgument:
    typ: VyperType


@dataclass(frozen=True)
class FoldedArgument:
    value: Any


PreparedDataSource = Union[PreparedValue, DataView]
PreparedArg = Union[PreparedValue, DataView, PreparedList, TypeArgument, FoldedArgument]


@dataclass(frozen=True)
class ValuePolicy:
    pass


@dataclass(frozen=True)
class DataSourcePolicy:
    allowed_views: frozenset[DataViewKind]
    unsupported_message: Optional[str] = None


@dataclass(frozen=True)
class LengthPolicy:
    allowed_views: frozenset[DataViewKind]


@dataclass(frozen=True)
class ValueListPolicy:
    pass


@dataclass(frozen=True)
class FoldedPolicy:
    pass


ArgPolicy = Union[ValuePolicy, DataSourcePolicy, LengthPolicy, ValueListPolicy, FoldedPolicy]

VALUE = ValuePolicy()
VALUE_LIST = ValueListPolicy()
FOLDED = FoldedPolicy()


def data_source(
    *allowed_views: DataViewKind, unsupported_message: Optional[str] = None
) -> DataSourcePolicy:
    return DataSourcePolicy(frozenset(allowed_views), unsupported_message)


def length_source(*allowed_views: DataViewKind) -> LengthPolicy:
    return LengthPolicy(frozenset(allowed_views))


def classify_data_view(
    node: vy_ast.VyperNode,
) -> Optional[tuple[DataViewKind, Optional[vy_ast.VyperNode]]]:
    """Return the raw-view kind and its runtime address expression, if any."""
    if not isinstance(node, vy_ast.Attribute):
        return None

    if isinstance(node.value, vy_ast.Name):
        if node.value.id == "msg" and node.attr == "data":
            return DataViewKind.CALLDATA, None
        if node.value.id == "self" and node.attr == "code":
            return DataViewKind.SELF_CODE, None

    if node.attr == "code" and isinstance(node.value._metadata.get("type"), AddressT):
        return DataViewKind.EXTERNAL_CODE, node.value

    return None
