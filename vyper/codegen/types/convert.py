# transition module to convert from new types to old types

import vyper.codegen.types as old
import vyper.semantics.types as new
from vyper.exceptions import InvalidType


def new_type_to_old_type(typ: new.VyperType) -> old.NodeType:
    if typ._is_prim_word:
        return old.BaseType(typ._id)
    if isinstance(typ, new.InterfaceT):
        return old.InterfaceType(typ._id)
    if isinstance(typ, new.BytesT):
        return old.ByteArrayType(typ.length)
    if isinstance(typ, new.StringT):
        return old.StringType(typ.length)
    if isinstance(typ, new.SArrayT):
        return old.SArrayType(new_type_to_old_type(typ.value_type), typ.length)
    if isinstance(typ, new.DArrayT):
        return old.DArrayType(new_type_to_old_type(typ.value_type), typ.length)
    if isinstance(typ, new.TupleT):
        assert isinstance(typ.value_type, tuple)  # mypy hint
        return old.TupleType([new_type_to_old_type(t) for t in typ.value_type])
    if isinstance(typ, new.StructT):
        return old.StructType(
            {n: new_type_to_old_type(t) for (n, t) in typ.members.items()}, typ._id
        )
    if isinstance(typ, new.EnumT):
        return old.EnumType(typ._id, typ.members.copy())
    if isinstance(typ, new.HashMapT):
        return old.MappingType(
            new_type_to_old_type(typ.key_type), new_type_to_old_type(typ.value_type)
        )
    raise InvalidType(f"unknown type {typ}")
