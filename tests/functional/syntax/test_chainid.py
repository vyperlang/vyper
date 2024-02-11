import pytest

from vyper import compiler
from vyper.compiler.settings import Settings
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import TypeMismatch


@pytest.mark.parametrize("evm_version", list(EVM_VERSIONS))
def test_evm_version(evm_version):
    code = """
@external
def foo():
    a: uint256 = chain.id
    """
    settings = Settings(evm_version=evm_version)

    assert compiler.compile_code(code, settings=settings) is not None


fail_list = [
    (
        """
@external
def foo() -> int128[2]:
    return [3,chain.id]
    """,
        TypeMismatch,
    ),
    """
@external
def foo() -> decimal:
    x: int128 = as_wei_value(5, "finney")
    y: int128 = chain.id + 50
    return x / y
    """,
    """
@external
def foo():
    x: int128 = 7
    y: int128 = min(x, chain.id)
    """,
    """
a: HashMap[uint256, int128]

@external
def add_record():
    self.a[chain.id] = chain.id + 20
    """,
    """
a: HashMap[int128, uint256]

@external
def add_record():
    self.a[chain.id] = chain.id + 20
    """,
    (
        """
@external
def foo(inp: Bytes[10]) -> Bytes[3]:
    return slice(inp, chain.id, -3)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_chain_fail(bad_code):
    if isinstance(bad_code, tuple):
        with pytest.raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with pytest.raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@external
@view
def get_chain_id() -> uint256:
    return chain.id
    """,
    """
@external
@view
def check_chain_id(c: uint256) -> bool:
    return chain.id == c
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_chain_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_chainid_operation(get_contract_with_gas_estimation):
    code = """
@external
@view
def get_chain_id() -> uint256:
    return chain.id
    """
    c = get_contract_with_gas_estimation(code)
    assert c.get_chain_id() == 131277322940537  # Default value of py-evm
