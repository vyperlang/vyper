from eth.codecs import abi

from vyper.utils import method_id


def test_revert_reason(env, tx_failed, get_contract):
    reverty_code = """
@external
def foo():
    data: Bytes[4] = method_id("NoFives()")
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives()")

    with tx_failed(exc_text=revert_bytes.hex()):
        get_contract(reverty_code).foo()


def test_revert_reason_typed(env, tx_failed, get_contract):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    data: Bytes[100] = _abi_encode(val, method_id=method_id("NoFives(uint256)"))
    raw_revert(data)
    """

    revert_bytes = method_id("NoFives(uint256)") + abi.encode("(uint256)", (5,))

    with tx_failed(exc_text=revert_bytes.hex()):
        get_contract(reverty_code).foo()


def test_revert_reason_typed_no_variable(env, tx_failed, get_contract):
    reverty_code = """
@external
def foo():
    val: uint256 = 5
    raw_revert(_abi_encode(val, method_id=method_id("NoFives(uint256)")))
    """

    revert_bytes = method_id("NoFives(uint256)") + abi.encode("(uint256)", (5,))

    with tx_failed(exc_text=revert_bytes.hex()):
        get_contract(reverty_code).foo()
