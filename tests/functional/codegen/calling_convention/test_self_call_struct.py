from decimal import Decimal


def test_call_to_self_struct(w3, get_contract):
    code = """
struct MyStruct:
    e1: decimal
    e2: uint256

@internal
@view
def get_my_struct(_e1: decimal, _e2: uint256) -> MyStruct:
    return MyStruct(e1=_e1, e2=_e2)

@external
@view
def wrap_get_my_struct_WORKING(_e1: decimal) -> MyStruct:
    testing: MyStruct = self.get_my_struct(_e1, block.timestamp)
    return testing

@external
@view
def wrap_get_my_struct_BROKEN(_e1: decimal) -> MyStruct:
    return self.get_my_struct(_e1, block.timestamp)
    """
    c = get_contract(code)
    assert c.wrap_get_my_struct_WORKING(Decimal("0.1")) == (
        Decimal("0.1"),
        w3.eth.get_block(w3.eth.block_number)["timestamp"],
    )
    assert c.wrap_get_my_struct_BROKEN(Decimal("0.1")) == (
        Decimal("0.1"),
        w3.eth.get_block(w3.eth.block_number)["timestamp"],
    )


def test_call_to_self_struct_2(get_contract):
    code = """
struct MyStruct:
    e1: decimal

@internal
@view
def get_my_struct(_e1: decimal) -> MyStruct:
    return MyStruct(e1=_e1)

@external
@view
def wrap_get_my_struct_WORKING(_e1: decimal) -> MyStruct:
    testing: MyStruct = self.get_my_struct(_e1)
    return testing

@external
@view
def wrap_get_my_struct_BROKEN(_e1: decimal) -> MyStruct:
    return self.get_my_struct(_e1)
    """
    c = get_contract(code)
    assert c.wrap_get_my_struct_WORKING(Decimal("0.1")) == (Decimal("0.1"),)
    assert c.wrap_get_my_struct_BROKEN(Decimal("0.1")) == (Decimal("0.1"),)
