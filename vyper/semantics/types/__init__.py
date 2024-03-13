from . import primitives, subscriptable, user
from .base import TYPE_T, VOID_TYPE, KwargSettings, VyperType, is_type_t, map_void
from .bytestrings import BytesT, StringT, _BytestringT
from .function import MemberFunctionT
from .module import InterfaceT
from .primitives import AddressT, BoolT, BytesM_T, DecimalT, IntegerT, SelfT
from .subscriptable import DArrayT, HashMapT, SArrayT, TupleT
from .user import EventT, FlagT, StructT


def _get_primitive_types():
    res = [BoolT(), DecimalT()]

    res.extend(IntegerT.all())
    res.extend(BytesM_T.all())

    # order of the types matters!
    # parsing of literal hex: prefer address over bytes20
    res.append(AddressT())

    # note: since bytestrings are parametrizable, the *class* objects
    # are in the namespace instead of concrete type objects.
    res.extend([BytesT, StringT])

    ret = {t._id: t for t in res}
    ret.update(_get_sequence_types())

    return ret


def _get_sequence_types():
    # since these guys are parametrizable, the *class* objects
    # are in the namespace instead of concrete type objects.

    res = [HashMapT, DArrayT]

    ret = {t._id: t for t in res}

    # (static) arrays and tuples are special types which don't show up
    # in the type annotation itself.
    # since we don't have special handling of annotations in the parser,
    # break a dependency cycle by injecting these into the namespace with
    # mangled names (that no user can create).
    ret["$SArrayT"] = SArrayT
    ret["$TupleT"] = TupleT

    return ret


# note: it might be good to make this a frozen dict of some sort
PRIMITIVE_TYPES = _get_primitive_types()
