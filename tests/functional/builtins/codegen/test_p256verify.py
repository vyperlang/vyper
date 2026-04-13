import contextlib

from eth_account._utils.signing import to_bytes32

from tests.utils import check_precompile_asserts
from vyper.compiler.settings import OptimizationLevel


def test_p256verify_test(get_contract):
    p256verify_test = """
@external
def test_p256verify_ref() -> Bytes[32]:
    x: Bytes[32] = raw_call(0x0000000000000000000000000000000000000100, x"3535353535353535353535353535353535353535353535353535353535353535da594cbeb5c0765ee974e96f7bce8d4c8e12d4d3464ef99076987bad34fd6d460c66de5263b81a3a95f9ffb3672bff38edee168f7e364740035e28e47c3fce451bec1250aa8f78275f99a6663688f31085848d0ed92f1203e447125f927b7486976e19d2eecfd3d40f935f10be09e63bcbc8a24a71efb67848d97725c3a0dc73", max_outsize=32)
    return x

@external
def test_p256verify(h: bytes32, r: bytes32, s: bytes32, qx: bytes32, qy: bytes32) -> bool:
    return p256verify(h, r, s, qx, qy)

@external
def test_p256verify_uints(h: bytes32, r: uint256, s: uint256, qx: uint256, qy: uint256) -> bool:
    return p256verify(h, r, s, qx, qy)

@external
def test_p256verify2() -> bool:
    return p256verify(0x3535353535353535353535353535353535353535353535353535353535353535,
                      0xda594cbeb5c0765ee974e96f7bce8d4c8e12d4d3464ef99076987bad34fd6d46,
                      0x0c66de5263b81a3a95f9ffb3672bff38edee168f7e364740035e28e47c3fce45,
                      0x1bec1250aa8f78275f99a6663688f31085848d0ed92f1203e447125f927b7486,
                      0x976e19d2eecfd3d40f935f10be09e63bcbc8a24a71efb67848d97725c3a0dc73)

@external
def test_p256verify_uints2() -> bool:
    return p256verify(0x3535353535353535353535353535353535353535353535353535353535353535,
                      98761980054170270937408382104354891893286643426216415950372463285192538025286,
                      5609506992512858306573062793366037412769796088996449907268665207118188498501,
                      12629549225227976241356111515927596904304931295610341061646093821237457024134,
                      68493771543596137459367957359258469689508944250940501394294780199949563911283)

    """

    c = get_contract(p256verify_test)

    h = b"\x35" * 32
    # signature and public key for secret key `b"\x46" * 32`
    r = 98761980054170270937408382104354891893286643426216415950372463285192538025286
    s = 5609506992512858306573062793366037412769796088996449907268665207118188498501
    qx = 12629549225227976241356111515927596904304931295610341061646093821237457024134
    qy = 68493771543596137459367957359258469689508944250940501394294780199949563911283

    assert c.test_p256verify_ref() == b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"
    assert c.test_p256verify(h, to_bytes32(r), to_bytes32(s), to_bytes32(qx), to_bytes32(qy)) is True
    assert c.test_p256verify_uints(h, r, s, qx, qy) is True
    assert c.test_p256verify2() is True
    assert c.test_p256verify_uints2() is True

    print("Passed p256verify test")


def test_invalid_signature(get_contract):
    code = """
dummies: HashMap[address, HashMap[address, uint256]]

@external
def test_p256verify(hash: bytes32) -> bool:
    # read from hashmap to put garbage in 0 memory location
    r: uint256 = self.dummies[msg.sender][msg.sender]
    # 0 is an invalid value for `s`, `qx`, and `qy`! Precompile will return
    # empty bytes.
    return p256verify(hash, r, 0, 0, 0)
    """
    c = get_contract(code)
    hash_ = bytes(i for i in range(32))
    assert c.test_p256verify(hash_) is False


# slightly more subtle example: get_r() stomps memory location 0,
# so this tests that the output buffer stays clean during p256verify()
# builtin execution.
def test_invalid_signature2(get_contract):
    code = """

owner: immutable(address)

@deploy
def __init__():
    owner = 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf

@internal
def get_r() -> uint256:
    assert owner == owner # force a dload to write at index 0 of memory
    return 0

@payable
@external
def test_p256verify() -> bool:
    assert p256verify(empty(bytes32), self.get_r(), 0, 0, 0) == False
    return True
    """
    c = get_contract(code)
    assert c.test_p256verify() is True


def test_p256verify_oog_handling(env, get_contract, tx_failed, optimize, experimental_codegen):
    code = """
@external
@view
def do_p256verify(hash: bytes32, r: uint256, s: uint256, qx: uint256, qy: uint256) -> bool:
    return p256verify(hash, r, s, qx, qy)
    """
    check_precompile_asserts(code)

    c = get_contract(code)

    h = b"\x35" * 32
    # signature and public key for secret key `b"\x46" * 32`
    r = 98761980054170270937408382104354891893286643426216415950372463285192538025286
    s = 5609506992512858306573062793366037412769796088996449907268665207118188498501
    qx = 12629549225227976241356111515927596904304931295610341061646093821237457024134
    qy = 68493771543596137459367957359258469689508944250940501394294780199949563911283

    assert c.do_p256verify(h, r, s, qx, qy) is True

    gas_used = env.last_result.gas_used

    if optimize == OptimizationLevel.NONE and not experimental_codegen:
        # if optimizations are off, enough gas is used by the contract
        # that the gas provided to p256verify (63/64ths rule) is enough
        # for it to succeed
        ctx = contextlib.nullcontext
    else:
        # in other cases, the gas forwarded is small enough for p256verify
        # to fail with oog, which we handle by reverting.
        ctx = tx_failed

    with ctx():
        # provide enough spare gas for the top-level call to not oog but
        # not enough for p256verify to succeed
        c.do_p256verify(h, r, s, qx, qy, gas=gas_used)
