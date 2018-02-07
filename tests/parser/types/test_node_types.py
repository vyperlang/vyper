from pytest import raises

from vyper.types import (
    BaseType,
    ByteArrayType,
    ListType,
    MappingType,
    NullType,
    StructType,
    TupleType,
    canonicalize_type,
    get_size_of_type,
)


def test_null_type():
    node1 = NullType()
    node2 = NullType()

    assert node1 == node2


def test_bytearray_node_type():

    node1 = ByteArrayType(12)
    node2 = ByteArrayType(12)

    assert node1 == node2

    node3 = ByteArrayType(13)
    node4 = BaseType('num')

    assert node1 != node3
    assert node1 != node4


def test_mapping_node_types():

    with raises(Exception):
        MappingType(int, int)

    node1 = MappingType(BaseType('num'), BaseType('num'))
    node2 = MappingType(BaseType('num'), BaseType('num'))
    assert node1 == node2
    assert str(node1) == "num[num]"


def test_tuple_node_types():
    node1 = TupleType([BaseType('num'), BaseType('decimal')])
    node2 = TupleType([BaseType('num'), BaseType('decimal')])

    assert node1 == node2
    assert str(node1) == "(num, decimal)"


def test_canonicalize_type():
    # Non-basetype not allowed
    with raises(Exception):
        canonicalize_type(int)
    # List of byte arrays not allowed
    a = ListType(ByteArrayType(12), 2)
    with raises(Exception):
        canonicalize_type(a)
    # Test ABI format of multiple args.
    c = TupleType([BaseType('num'), BaseType('address')])
    assert canonicalize_type(c) == "(int128,address)"


def test_get_size_of_type():
    assert get_size_of_type(BaseType('num')) == 1
    assert get_size_of_type(ByteArrayType(12)) == 3
    assert get_size_of_type(ByteArrayType(33)) == 4
    assert get_size_of_type(ListType(BaseType('num'), 10)) == 10

    _tuple = TupleType([BaseType('num'), BaseType('decimal')])
    assert get_size_of_type(_tuple) == 2

    _struct = StructType({
        'a': BaseType('num'),
        'b': BaseType('decimal')
    })
    assert get_size_of_type(_struct) == 2

    # Don't allow unknow types.
    with raises(Exception):
        get_size_of_type(int)

    # Maps are not supported for function arguments or outputs
    with raises(Exception):
        get_size_of_type(MappingType(BaseType('num'), BaseType('num')))
