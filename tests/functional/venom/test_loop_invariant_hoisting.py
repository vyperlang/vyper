import pytest

from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.venom.passes.loop_invariant_hosting import LoopInvariantHoisting


@pytest.mark.parametrize("iterations", [2, 10, 100])
def test_loop_invariant_sload_reduces_gas(get_contract, env, evm_version, monkeypatch, iterations):
    code = """
value: uint256

@deploy
def __init__(initial_value: uint256):
    self.value = initial_value

@external
@view
def total(iterations: uint256) -> uint256:
    result: uint256 = 0
    for i: uint256 in range(iterations, bound=100):
        result += self.value
    return result
"""
    # Hoisting is part of O3; keep every other compiler setting/pass identical.
    settings = Settings(
        optimize=OptimizationLevel.O3, experimental_codegen=True, evm_version=evm_version
    )
    value = 7
    hoisted = get_contract(code, value, compiler_settings=settings)
    with monkeypatch.context() as patch:
        patch.setattr(LoopInvariantHoisting, "run_pass", lambda self, **kwargs: None)
        unhoisted = get_contract(code, value, compiler_settings=settings)

    assert hoisted.total(iterations) == iterations * value
    hoisted_gas = env.last_result.gas_used
    assert unhoisted.total(iterations) == iterations * value
    unhoisted_gas = env.last_result.gas_used

    assert hoisted_gas < unhoisted_gas


@pytest.mark.parametrize("iterations", [0, 2, 10, 100])
def test_loop_invariant_memory_read(
    get_contract, env, evm_version, monkeypatch, keccak, iterations
):
    code = """
@external
@pure
def hashes(data: Bytes[64], iterations: uint256) -> DynArray[bytes32, 100]:
    result: DynArray[bytes32, 100] = []
    for i: uint256 in range(iterations, bound=100):
        result.append(keccak256(data))
    return result
"""
    # The loop writes result, but the hash only reads the separate data allocation.
    settings = Settings(
        optimize=OptimizationLevel.O3, experimental_codegen=True, evm_version=evm_version
    )
    hoisted = get_contract(code, compiler_settings=settings)
    with monkeypatch.context() as patch:
        patch.setattr(LoopInvariantHoisting, "run_pass", lambda self, **kwargs: None)
        unhoisted = get_contract(code, compiler_settings=settings)

    data = b"loop-invariant memory"
    expected = [keccak(data)] * iterations
    assert hoisted.hashes(data, iterations) == expected
    hoisted_gas = env.last_result.gas_used
    assert unhoisted.hashes(data, iterations) == expected
    unhoisted_gas = env.last_result.gas_used

    if iterations > 0:
        assert hoisted_gas < unhoisted_gas
