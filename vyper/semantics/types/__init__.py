from . import subscriptable, user, primitives
from .base import VyperType, DataLocation, TYPE_T, VarInfo
from .subscriptable import HashMapT, SArrayT, TupleT, DArrayT
from .user import EnumT, InterfaceT, EventT, StructT
from .primitives import AddressT, BoolT, BytesM_T, IntegerT, DecimalT
from .bytestrings import BytesT, StringT


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
