from pytest import raises

from vyper.codegen.types import (
    BaseType,
    ByteArrayType,
    MappingType,
    SArrayType,
    StructType,
    TupleType,
)


def test_bytearray_node_type():

    node1 = ByteArrayType(12)
    node2 = ByteArrayType(12)

    assert node1 == node2

    node3 = ByteArrayType(13)
    node4 = BaseType("int128")

    assert node1 != node3
    assert node1 != node4


def test_mapping_node_types():

    with raises(Exception):
        MappingType(int, int)

    node1 = MappingType(BaseType("int128"), BaseType("int128"))
    node2 = MappingType(BaseType("int128"), BaseType("int128"))
    assert node1 == node2
    assert str(node1) == "HashMap[int128, int128]"


def test_tuple_node_types():
    node1 = TupleType([BaseType("int128"), BaseType("decimal")])
    node2 = TupleType([BaseType("int128"), BaseType("decimal")])

    assert node1 == node2
    assert str(node1) == "(int128, decimal)"


def test_canonicalize_type():
    # TODO add more types

    # Test ABI format of multiple args.
    c = TupleType([BaseType("int128"), BaseType("address")])
    assert c.abi_type.selector_name() == "(int128,address)"


def test_type_storage_sizes():
    assert BaseType("int128").storage_size_in_words == 1
    assert ByteArrayType(12).storage_size_in_words == 2
    assert ByteArrayType(33).storage_size_in_words == 3
    assert SArrayType(BaseType("int128"), 10).storage_size_in_words == 10

    _tuple = TupleType([BaseType("int128"), BaseType("decimal")])
    assert _tuple.storage_size_in_words == 2

    _struct = StructType({"a": BaseType("int128"), "b": BaseType("decimal")}, "Foo")
    assert _struct.storage_size_in_words == 2

    # Don't allow unknown types.
    with raises(Exception):
        _ = int.storage_size_in_words

    # Maps are not supported for function arguments or outputs
    with raises(Exception):
        _ = MappingType(BaseType("int128"), BaseType("int128")).storage_size_in_words
