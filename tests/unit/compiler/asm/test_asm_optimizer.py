import pytest

from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings

codes = [
    """
s: uint256

@internal
def ctor_only():
    self.s = 1

@internal
def runtime_only():
    self.s = 2

@external
def bar():
    self.runtime_only()

@external
def __init__():
    self.ctor_only()
    """,
    # code with nested function in it
    """
s: uint256

@internal
def runtime_only():
    self.s = 1

@internal
def foo():
    self.runtime_only()

@internal
def ctor_only():
    self.s += 1

@external
def bar():
    self.foo()

@external
def __init__():
    self.ctor_only()
    """,
    # code with loop in it, these are harder for dead code eliminator
    """
s: uint256

@internal
def ctor_only():
    self.s = 1

@internal
def runtime_only():
    for i in range(10):
        self.s += 1

@external
def bar():
    self.runtime_only()

@external
def __init__():
    self.ctor_only()
    """,
]


# check dead code eliminator works on unreachable functions
@pytest.mark.parametrize("code", codes)
def test_dead_code_eliminator(code):
    c = CompilerData(code, settings=Settings(optimize=OptimizationLevel.NONE))

    # get the labels
    initcode_asm = [i for i in c.assembly if isinstance(i, str)]
    runtime_asm = [i for i in c.assembly_runtime if isinstance(i, str)]

    ctor_only = "ctor_only()"
    runtime_only = "runtime_only()"

    # qux reachable from unoptimized initcode, foo not reachable.
    assert any(ctor_only in instr for instr in initcode_asm)
    assert all(runtime_only not in instr for instr in initcode_asm)

    # all labels should be in unoptimized runtime asm
    for s in (ctor_only, runtime_only):
        assert any(s in instr for instr in runtime_asm)

    c = CompilerData(code, settings=Settings(optimize=OptimizationLevel.GAS))
    initcode_asm = [i for i in c.assembly if isinstance(i, str)]
    runtime_asm = [i for i in c.assembly_runtime if isinstance(i, str)]

    # ctor only label should not be in runtime code
    assert all(ctor_only not in instr for instr in runtime_asm)

    # runtime only label should not be in initcode asm
    assert all(runtime_only not in instr for instr in initcode_asm)
