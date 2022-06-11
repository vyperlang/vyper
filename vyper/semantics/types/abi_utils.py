from vyper.semantics.types.bases import BaseTypeDefinition
from vyper.semantics.types.indexable.sequence import (
    ArrayDefinition,
    DynamicArrayDefinition,
    TupleDefinition,
)
from vyper.semantics.types.user.struct import StructDefinition


def json_abi_type(type_: BaseTypeDefinition, name: str = None) -> dict:
    """
    Generate the JSON ABI type for a given type.
    cf. https://docs.soliditylang.org/en/v0.8.14/abi-spec.html#json
    """

    def finalize(return_value):
        if name is not None:
            return {"name": name, **return_value}
        return return_value

    """
    > The canonical type is determined until a tuple type is reached and
      the string description up to that point is stored in type prefix
      with the word tuple,
    """
    if isinstance(type_, TupleDefinition):
        components = [json_abi_type(t) for t in type_._member_types]
        return finalize({"type": "tuple", "components": components})

    # struct is similar to tuple but everything has names
    if isinstance(type_, StructDefinition):
        components = [json_abi_type(t, name=k) for k, t in type_.members.items()]
        return finalize({"type": "tuple", "components": components})

    """
    > i.e. it will be tuple followed by a sequence of [] and [k] with
      integers k.
    """
    if isinstance(type_, (ArrayDefinition, DynamicArrayDefinition)):
        ret = json_abi_type(type_.value_type)
        if isinstance(type_, DynamicArrayDefinition):
            suffix = "[]"
        else:
            suffix = f"[{type_.length}]"

        # modify in place
        ret.setdefault("name", "")
        ret["type"] += suffix
        return finalize(ret)

    ret = {"type": type_.abi_type.selector_name()}
    return finalize(ret)
