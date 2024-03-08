from typing import Type

import pytest
from eth_tester.exceptions import TransactionFailed
from web3 import Web3

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.exceptions import NamespaceCollision, StructureException, VyperException

# For reproducibility, use precompiled data of `hello: public(uint256)` using vyper 0.3.1
PRECOMPILED_ABI = """[{"stateMutability": "view", "type": "function", "name": "hello", "inputs": [], "outputs": [{"name": "", "type": "uint256"}], "gas": 2460}]"""  # noqa: E501
PRECOMPILED_BYTECODE = """0x61004456600436101561000d57610035565b60046000601c376000513461003b576319ff1d2181186100335760005460e052602060e0f35b505b60006000fd5b600080fd5b61000461004403610004600039610004610044036000f3"""  # noqa: E501
PRECOMPILED_BYTECODE_RUNTIME = """0x600436101561000d57610035565b60046000601c376000513461003b576319ff1d2181186100335760005460e052602060e0f35b505b60006000fd5b600080fd"""  # noqa: E501
PRECOMPILED = bytes.fromhex(PRECOMPILED_BYTECODE_RUNTIME[2:])


def _deploy_precompiled_contract(w3: Web3):
    Precompiled = w3.eth.contract(abi=PRECOMPILED_ABI, bytecode=PRECOMPILED_BYTECODE)
    tx_hash = Precompiled.constructor().transact()
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    address = tx_receipt["contractAddress"]
    return w3.eth.contract(address=address, abi=PRECOMPILED_ABI)


@pytest.mark.parametrize(
    ("start", "length", "expected"), [(0, 5, PRECOMPILED[:5]), (5, 10, PRECOMPILED[5:][:10])]
)
def test_address_code_slice(start: int, length: int, expected: bytes, w3: Web3, get_contract):
    code = f"""
@external
def code_slice(x: address) -> Bytes[{length}]:
    return slice(x.code, {start}, {length})
"""
    contract = get_contract(code)
    precompiled_contract = _deploy_precompiled_contract(w3)
    actual = contract.code_slice(precompiled_contract.address)
    assert actual == expected


def test_address_code_runtime_error_slice_too_long(w3: Web3, get_contract):
    start = len(PRECOMPILED) - 5
    length = 10
    code = f"""
@external
def code_slice(x: address) -> Bytes[{length}]:
    return slice(x.code, {start}, {length})
"""
    contract = get_contract(code)
    precompiled_contract = _deploy_precompiled_contract(w3)
    with pytest.raises(TransactionFailed):
        contract.code_slice(precompiled_contract.address)


def test_address_code_runtime_error_no_code(get_contract):
    code = """
@external
def code_slice(x: address) -> Bytes[4]:
    return slice(x.code, 0, 4)
"""
    contract = get_contract(code)
    with pytest.raises(TransactionFailed):
        contract.code_slice(b"\x00" * 20)


@pytest.mark.parametrize(
    ("bad_code", "error_type", "error_message"),
    [
        (
            # `(address).code` without `slice`
            """
@external
def code_slice(x: address) -> uint256:
    y: uint256 = convert(x.code, uint256)
    return y
""",
            StructureException,
            "(address).code is only allowed inside of a slice function with a constant length",
        ),
        (
            """
a: HashMap[Bytes[4], uint256]

@external
def foo(x: address):
    self.a[x.code] += 1
""",
            StructureException,
            "(address).code is only allowed inside of a slice function with a constant length",
        ),
        (
            # `len` not supported
            """
@external
def code_slice(x: address) -> uint256:
    y: uint256 = len(x.code)
    return y
""",
            StructureException,
            "(address).code is only allowed inside of a slice function with a constant length",
        ),
        (
            # `slice` with non static length
            """
@external
def code_slice(x: address, y: uint256) -> Bytes[4]:
    z: Bytes[4] = slice(x.code, 0, y)
    return z
""",
            StructureException,
            "(address).code is only allowed inside of a slice function with a constant length",
        ),
        (
            # `self.code` is already defined since `self` is address
            """
code: public(Bytes[4])
""",
            NamespaceCollision,
            "Member 'code' already exists in self",
        ),
    ],
)
def test_address_code_compile_error(
    bad_code: str, error_type: Type[VyperException], error_message: str
):
    with pytest.raises(error_type) as excinfo:
        compiler.compile_code(bad_code)
    assert excinfo.value.message == error_message


@pytest.mark.parametrize(
    "code",
    [
        # Environment variable
        """
@external
def foo() -> Bytes[4]:
    return slice(msg.sender.code, 0, 4)
""",
        # User defined struct
        """
struct S:
    a: address

@external
def foo(s: S) -> Bytes[4]:
    return slice(s.a.code, 0, 4)
""",
        # External contract call
        """
interface Test:
    def out_literals() -> address : view

@external
def foo(x: address) -> Bytes[4]:
    return slice((staticcall Test(x).out_literals()).code, 0, 4)
""",
    ],
)
def test_address_code_compile_success(code: str):
    compiler.compile_code(code)


def test_address_code_self_success(get_contract, optimize):
    code = """
code_deployment: public(Bytes[32])

@deploy
def __init__():
    self.code_deployment = slice(self.code, 0, 32)

@external
def code_runtime() -> Bytes[32]:
    return slice(self.code, 0, 32)
"""
    contract = get_contract(code)
    settings = Settings(optimize=optimize)
    code_compiled = compiler.compile_code(
        code, output_formats=["bytecode", "bytecode_runtime"], settings=settings
    )
    assert contract.code_deployment() == bytes.fromhex(code_compiled["bytecode"][2:])[:32]
    assert contract.code_runtime() == bytes.fromhex(code_compiled["bytecode_runtime"][2:])[:32]


def test_address_code_self_runtime_error_deployment(get_contract):
    code = """
dummy: public(Bytes[1000000])

@deploy
def __init__():
    self.dummy = slice(self.code, 0, 1000000)
"""
    with pytest.raises(TransactionFailed):
        get_contract(code)


def test_address_code_self_runtime_error_runtime(get_contract):
    code = """
@external
def code_runtime() -> Bytes[1000000]:
    return slice(self.code, 0, 1000000)
"""
    contract = get_contract(code)
    with pytest.raises(TransactionFailed):
        contract.code_runtime()
