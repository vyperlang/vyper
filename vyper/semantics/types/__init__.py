from . import subscriptable, user, primitives
from .base import VyperType, DataLocation, TYPE_T
from .subscriptable import ( HashMapT , SArrayT, TupleT, DArrayT,)
from .user import EnumT, InterfaceT, EventT, StructT
from .primitives import AddressT, BoolT, BytesM_T, IntegerT, DecimalT
from .bytestrings import BytesT, StringT


def get_primitive_types():
    ret = [AddressT(), BoolT(), DecimalT()]

    ret.extend(IntegerT.all())
    ret.extend(BytesM_T.all())

    return {t._id: t for t in ret}

def get_types():
    result = {}
    #result.update(user.USER_TYPES)
    result.update(get_primitive_types())

    return result
