from . import primitives, subscriptable, user
from .base import TYPE_T, DataLocation, VarInfo, VyperType
from .bytestrings import BytesT, StringT
from .primitives import AddressT, BoolT, BytesM_T, DecimalT, IntegerT
from .subscriptable import DArrayT, HashMapT, SArrayT, TupleT
from .user import EnumT, EventT, InterfaceT, StructT


def get_primitive_types():
    res = [AddressT(), BoolT(), DecimalT()]

    res.extend(IntegerT.all())
    res.extend(BytesM_T.all())

    return {t._id: t for t in res}


def get_types():
    result = {}
    # result.update(user.USER_TYPES)
    result.update(get_primitive_types())

    return result
