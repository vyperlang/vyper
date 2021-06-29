from pytest import raises

from vyper.old_codegen.types import (
    BaseType,
    ByteArrayType,
    ListType,
    MappingType,
    StructType,
    TupleType,
    canonicalize_type,
    get_size_of_type,
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
    # Non-basetype not allowed
    with raises(Exception):
        canonicalize_type(int)
    # List of byte arrays not allowed
    a = ListType(ByteArrayType(12), 2)
    with raises(Exception):
        canonicalize_type(a)
    # Test ABI format of multiple args.
    c = TupleType([BaseType("int128"), BaseType("address")])
    assert canonicalize_type(c) == "(int128,address)"


def test_get_size_of_type():
    assert get_size_of_type(BaseType("int128")) == 1
    assert get_size_of_type(ByteArrayType(12)) == 3
    assert get_size_of_type(ByteArrayType(33)) == 4
    assert get_size_of_type(ListType(BaseType("int128"), 10)) == 10

    _tuple = TupleType([BaseType("int128"), BaseType("decimal")])
    assert get_size_of_type(_tuple) == 2

    _struct = StructType({"a": BaseType("int128"), "b": BaseType("decimal")}, "Foo")
    assert get_size_of_type(_struct) == 2

    # Don't allow unknown types.
    with raises(Exception):
        get_size_of_type(int)

    # Maps are not supported for function arguments or outputs
    with raises(Exception):
        get_size_of_type(MappingType(BaseType("int128"), BaseType("int128")))
