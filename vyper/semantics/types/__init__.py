from . import indexable, user, value
from .abstract import SignedIntegerAbstractType, UnsignedIntegerAbstractType
from .bases import BasePrimitive
from .indexable.sequence import ArrayDefinition, TupleDefinition
from .user.event import Event
from .user.struct import StructDefinition
from .value.address import AddressDefinition
from .value.array_value import BytesArrayDefinition, StringDefinition
from .value.boolean import BoolDefinition
from .value.bytes_fixed import Bytes32Definition
from .value.numeric import (
    AbstractNumericDefinition,
    DecimalDefinition,
    Int128Definition,
    Uint256Definition,
)

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
