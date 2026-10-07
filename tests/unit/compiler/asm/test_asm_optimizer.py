import pytest

from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.assembler.instructions import CONST, CONSTREF, PUSH_OFST, PUSHLABEL, Label
from vyper.evm.assembler.optimizer import (
    _merge_jumpdests,
    _prune_unreachable_code,
    _prune_unused_consts,
    optimize_assembly,
)

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


def test_prune_unreachable_code_keeps_consts():
    # CONST declarations produce no bytecode and can be referenced from
    # reachable code, so they must not be pruned along with dead code
    asm = ["REVERT", "PUSH0", CONST("some_const", 5), "PUSH0", Label("label_0")]

    assert _prune_unreachable_code(asm) is True
    assert asm == ["REVERT", CONST("some_const", 5), Label("label_0")]

    assert _prune_unreachable_code(asm) is False, "should not return True as no changes were made"


def test_prune_unused_consts():
    asm = [CONST("used", 5), CONST("unused", 6), PUSH_OFST(CONSTREF("used"), 0), Label("label_0")]

    assert _prune_unused_consts(asm) is True
    assert asm == [CONST("used", 5), PUSH_OFST(CONSTREF("used"), 0), Label("label_0")]

    assert _prune_unused_consts(asm) is False, "should not return True as no changes were made"


def test_dead_consts_are_pruned():
    # a CONST declared in unreachable code survives dead code elimination if
    # reachable code still refers to it, and is removed otherwise
    asm = [
        PUSHLABEL(Label("label_0")),
        "JUMP",
        CONST("used", 5),
        CONST("unused", 6),
        Label("label_0"),
        PUSH_OFST(CONSTREF("used"), 0),
        "STOP",
    ]

    optimize_assembly(asm)

    assert asm == [
        PUSHLABEL(Label("label_0")),
        "JUMP",
        CONST("used", 5),
        Label("label_0"),
        PUSH_OFST(CONSTREF("used"), 0),
        "STOP",
    ]
