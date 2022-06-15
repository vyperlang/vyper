from . import indexable, user, value
from .abstract import ArrayValueAbstractType, SignedIntegerAbstractType, UnsignedIntegerAbstractType
from .bases import BasePrimitive, BaseTypeDefinition, DataLocation, ValueTypeDefinition
from .indexable.mapping import MappingDefinition
from .indexable.sequence import (
    ArrayDefinition,
    DynamicArrayDefinition,
    DynamicArrayPrimitive,
    TupleDefinition,
)
from .user.enum import EnumDefinition
from .user.event import Event
from .user.interface import InterfaceDefinition
from .user.struct import StructDefinition
from .value.address import AddressDefinition
from .value.array_value import BytesArrayDefinition, StringDefinition
from .value.boolean import BoolDefinition
from .value.bytes_fixed import Bytes32Definition, BytesMDefinition
from .value.numeric import Int128Definition  # type: ignore
from .value.numeric import Uint256Definition  # type: ignore
from .value.numeric import AbstractNumericDefinition, DecimalDefinition

# any more?


def get_primitive_types():
    result = {}

    for module in (indexable, value):
        submodules = [
            v
            for v in module.__dict__.values()
            if getattr(v, "__package__", None) == module.__package__
        ]
        for item in submodules:
            result.update(
                (v._id, v)
                for v in item.__dict__.values()
                if isinstance(getattr(v, "_id", None), str) and issubclass(v, BasePrimitive)
            )

    return result


def get_types():
    result = {}
    result.update(user.USER_TYPES)
    result.update(get_primitive_types())

    return result
