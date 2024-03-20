from pytest import raises

from vyper.semantics.types import (
    AddressT,
    BytesT,
    DecimalT,
    HashMapT,
    IntegerT,
    SArrayT,
    StructT,
    TupleT,
)

# TODO: this module should be merged in with other tests/functional/semantics/types/ tests.


def test_bytearray_node_type():
    node1 = BytesT(12)
    node2 = BytesT(12)

    assert node1 == node2

    node3 = BytesT(13)
    node4 = IntegerT(True, 128)

    assert node1 != node3
    assert node1 != node4


def test_mapping_node_types():
    node1 = HashMapT(IntegerT(True, 128), IntegerT(True, 128))
    node2 = HashMapT(IntegerT(True, 128), IntegerT(True, 128))
    assert node1 == node2
    assert str(node1) == "HashMap[int128, int128]"


def test_tuple_node_types():
    node1 = TupleT([IntegerT(True, 128), DecimalT()])
    node2 = TupleT([IntegerT(True, 128), DecimalT()])

    assert node1 == node2
    assert str(node1) == "(int128, decimal)"


def test_canonicalize_type():
    # TODO add more types

    # Test ABI format of multiple args.
    c = TupleT([IntegerT(True, 128), AddressT()])
    assert c.abi_type.selector_name() == "(int128,address)"


def test_type_storage_sizes():
    assert IntegerT(True, 128).storage_size_in_words == 1
    assert BytesT(12).storage_size_in_words == 2
    assert BytesT(33).storage_size_in_words == 3
    assert SArrayT(IntegerT(True, 128), 10).storage_size_in_words == 10

    tuple_ = TupleT([IntegerT(True, 128), DecimalT()])
    assert tuple_.storage_size_in_words == 2

    struct_ = StructT("Foo", {"a": IntegerT(True, 128), "b": DecimalT()})
    assert struct_.storage_size_in_words == 2

    # Don't allow unknown types.
    with raises(AttributeError):
        _ = int.storage_size_in_words
