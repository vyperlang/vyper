import pytest

from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.assembler import PUSHLABEL, Label
from vyper.evm.optimizer import _merge_jumpdests

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

@deploy
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

@deploy
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
    for i: uint256 in range(10):
        self.s += 1

@external
def bar():
    self.runtime_only()

@deploy
def __init__():
    self.ctor_only()
    """,
]


# check dead code eliminator works on unreachable functions
# CMC 2024-02-05 this is not really the asm eliminator anymore,
# it happens during function code generation in module.py. so we don't
# need to test this using asm anymore.
@pytest.mark.parametrize("code", codes)
def test_dead_code_eliminator(code):
    c = CompilerData(code, settings=Settings(optimize=OptimizationLevel.NONE))

    # get the labels
    initcode_labels = [i for i in c.assembly if isinstance(i, Label)]
    runtime_labels = [i for i in c.assembly_runtime if isinstance(i, Label)]

    ctor_only = "ctor_only()"
    runtime_only = "runtime_only()"

    # qux reachable from unoptimized initcode, foo not reachable.
    assert any(ctor_only in label.label for label in initcode_labels)
    assert all(runtime_only not in label.label for label in initcode_labels)

    assert any(runtime_only in label.label for label in runtime_labels)
    assert all(ctor_only not in label.label for label in runtime_labels)


def test_library_code_eliminator(make_input_bundle, experimental_codegen):
    library = """
@internal
def unused1():
    pass

@internal
def unused2():
    self.unused1()

@internal
def some_function():
    pass
    """
    code = """
import library

@external
def foo():
    library.some_function()
    """
    input_bundle = make_input_bundle({"library.vy": library})
    res = compile_code(code, input_bundle=input_bundle, output_formats=["asm_runtime"])
    asm = res["asm_runtime"]

    if not experimental_codegen:
        assert "some_function()" in asm  # Venom function inliner will remove this

    assert "unused1()" not in asm
    assert "unused2()" not in asm


def test_merge_jumpdests():
    asm = [PUSHLABEL(Label("label_0")), "JUMP", "PUSH0", Label("label_0"), Label("_label_0")]

    assert _merge_jumpdests(asm) is False, "should not return True as no changes were made"
