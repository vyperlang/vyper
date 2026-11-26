"""
Regression tests for GH issue #5414: a dead `phi` reaching
venom_to_assembly was never popped, stranding its incoming value on the
EVM stack. At -O3, SimplifyCFGPass runs after the last
RemoveUnusedVariablesPass and can remove the only use of a phi.
"""

import pytest

from vyper.compiler.settings import OptimizationLevel, Settings

OPT_LEVELS = [
    OptimizationLevel.NONE,
    OptimizationLevel.O1,
    OptimizationLevel.GAS,
    OptimizationLevel.CODESIZE,
    OptimizationLevel.O3,
]


def _venom_settings(compiler_settings, opt_level):
    return Settings(
        **dict(compiler_settings.__dict__, experimental_codegen=True, optimize=opt_level)
    )


@pytest.mark.requires_evm_version("cancun")
@pytest.mark.parametrize("opt_level", OPT_LEVELS)
def test_dead_phi_does_not_corrupt_caller_stack(get_contract, compiler_settings, opt_level):
    # the dead phi in `h1` (from the inlined `or` in `h0`) used to be
    # left on the stack across `ret`, shifting the caller's stack so that
    # `new_owner` was read as 1.
    code = """
s_b0: bool
s_b1: bool
s_t0: transient(uint256)
s_u0: uint256
s_buf: Bytes[128]
s_owner: public(address)

@deploy
def __init__():
    self.s_b0 = True
    self.s_owner = msg.sender

@internal
def h0(p0: uint256) -> uint256:
    v2: bool = self.s_b1
    if self.s_b0 or v2:
        p0 = 1 if (18446744073709551615 > self.s_t0) else 2
    return self.s_u0

@internal
def h1(p0: uint256) -> uint256:
    for i: uint256 in range(1, 3):
        if self.s_b1:
            break
    if self.s_b0:
        v2: uint256 = self.h0(p0)
    return p0 & 1

@external
def f_corrupt(a0: uint64, new_owner: address) -> address:
    self.s_u0 = self.h1(self.s_u0)
    self.s_u0 = self.h1(2)
    self.s_buf = b"hello"
    self.s_owner = new_owner
    return new_owner
    """
    c = get_contract(code, compiler_settings=_venom_settings(compiler_settings, opt_level))

    new_owner = "0x" + "11" * 20
    assert c.f_corrupt(303, new_owner) == new_owner
    assert c.s_owner() == new_owner


@pytest.mark.parametrize("opt_level", OPT_LEVELS)
def test_dead_phi_does_not_underflow(get_contract, compiler_settings, opt_level):
    # used to halt with a stack underflow at -O3
    code = """
s_b0: bool
s_flag: bool

@deploy
def __init__():
    self.s_b0 = True

@external
def f(a1: int256) -> bool:
    v1: int256 = (a1 if self.s_b0 else 0) if (self.s_flag or self.s_b0) else 0
    for i: uint256 in range(2):
        pass
    return True
    """
    c = get_contract(code, compiler_settings=_venom_settings(compiler_settings, opt_level))

    assert c.f(12345) is True


@pytest.mark.parametrize("opt_level", OPT_LEVELS)
def test_dead_phi_minimized_corrupt(get_contract, compiler_settings, opt_level):
    # minimized PoC 1 from the issue: each call to `h` used to leave its
    # dead phi on the caller's stack, so `new_owner` was read as 0.
    code = """
a: bool
b: bool
owner: public(address)

@internal
def h():
    v: uint256 = (1 if self.a else 2) if (self.b or self.a) else 0

@external
def f(new_owner: address) -> address:
    self.h()
    self.h()
    self.owner = new_owner
    return new_owner
    """
    c = get_contract(code, compiler_settings=_venom_settings(compiler_settings, opt_level))

    new_owner = "0x" + "11" * 20
    assert c.f(new_owner) == new_owner
    assert c.owner() == new_owner


@pytest.mark.parametrize("opt_level", OPT_LEVELS)
def test_dead_phi_minimized_underflow(get_contract, compiler_settings, opt_level):
    # minimized PoC 2 from the issue: used to underflow at -O3
    code = """
a: bool
b: bool

@external
def f() -> bool:
    v: uint256 = (1 if self.a else 0) if (self.b or self.a) else 0
    for i: uint256 in range(2):
        pass
    return True
    """
    c = get_contract(code, compiler_settings=_venom_settings(compiler_settings, opt_level))

    assert c.f() is True
