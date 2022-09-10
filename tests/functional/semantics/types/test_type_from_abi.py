import pytest

from vyper.exceptions import UnknownType
from vyper.semantics.types import get_primitive_types
from vyper.semantics.types.indexable.sequence import ArrayDefinition
from vyper.semantics.types.utils import get_type_from_abi

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(type_str):
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_abi({"type": type_str})

    assert isinstance(type_definition, primitive._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_arrays(type_str):
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_abi({"type": f"{type_str}[3]"})

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 3
    assert isinstance(type_definition.value_type, primitive._type)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_multidimensional_arrays(type_str):
    primitive = get_primitive_types()[type_str]

    type_definition = get_type_from_abi({"type": f"{type_str}[3][5]"})

    assert isinstance(type_definition, ArrayDefinition)
    assert type_definition.length == 5
    assert isinstance(type_definition.value_type, ArrayDefinition)
    assert type_definition.value_type.length == 3
    assert isinstance(type_definition.value_type.value_type, primitive._type)


@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
def test_invalid_index(idx):
    with pytest.raises(UnknownType):
        get_type_from_abi({"type": f"int128[{idx}]"})
