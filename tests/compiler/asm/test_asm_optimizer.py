import pytest

from vyper.compiler.phases import CompilerData

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


@pytest.mark.parametrize("code", codes)
def test_dead_code_eliminator(code):
    c = CompilerData(code, no_optimize=True)
    initcode_asm = [i for i in c.assembly if not isinstance(i, list)]
    runtime_asm = c.assembly_runtime

    ctor_only_label = "_sym_internal_ctor_only___"
    runtime_only_label = "_sym_internal_runtime_only___"

    # qux reachable from unoptimized initcode, foo not reachable.
    assert ctor_only_label + "_deploy" in initcode_asm
    assert runtime_only_label + "_deploy" not in initcode_asm

    # all labels should be in unoptimized runtime asm
    for s in (ctor_only_label, runtime_only_label):
        assert s + "_runtime" in runtime_asm

    c = CompilerData(code, no_optimize=False)
    initcode_asm = [i for i in c.assembly if not isinstance(i, list)]
    runtime_asm = c.assembly_runtime

    # ctor only label should not be in runtime code
    for instr in runtime_asm:
        if isinstance(instr, str):
            assert not instr.startswith(ctor_only_label), instr

    # runtime only label should not be in initcode asm
    for instr in initcode_asm:
        if isinstance(instr, str):
            assert not instr.startswith(runtime_only_label), instr
