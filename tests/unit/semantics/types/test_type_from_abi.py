import pytest

from vyper.exceptions import UnknownType
from vyper.semantics.types import PRIMITIVE_TYPES, SArrayT
from vyper.semantics.types.utils import type_from_abi

BASE_TYPES = ["int128", "uint256", "bool", "address", "bytes32"]


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types(type_str):
    base_t = PRIMITIVE_TYPES[type_str]
    type_t = type_from_abi({"type": type_str})

    assert base_t == type_t


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_arrays(type_str):
    base_t = PRIMITIVE_TYPES[type_str]
    type_t = type_from_abi({"type": f"{type_str}[3]"})

    assert type_t == SArrayT(base_t, 3)


@pytest.mark.parametrize("type_str", BASE_TYPES)
def test_base_types_as_multidimensional_arrays(type_str):
    base_t = PRIMITIVE_TYPES[type_str]

    type_t = type_from_abi({"type": f"{type_str}[3][5]"})

    assert type_t == SArrayT(SArrayT(base_t, 3), 5)


@pytest.mark.parametrize("idx", ["0", "-1", "0x00", "'1'", "foo", "[1]", "(1,)"])
def test_invalid_index(idx):
    with pytest.raises(UnknownType):
        type_from_abi({"type": f"int128[{idx}]"})
