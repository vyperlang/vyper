"""
Test that the Venom deploy code touches the immutables staging region
before the constructor body, so that msize-based dynamic allocation
("memtop") cannot return a pointer inside the uninitialized staging
region (GH issue 5053, cf. GH issue 3101).

The guard is an `istore` of zero to the last word of the immutables
region, emitted before constructor args are decoded. These tests check
the *optimized* deploy output, i.e. that the guard survives all venom
passes and reaches the final assembly.
"""

from vyper.compiler import compile_code
from vyper.compiler.settings import Settings

# constructor does dynamic (msize-based) allocation via raw_call(msg.data)
# *before* any immutable is assigned
CODE_WITH_IMMUTABLES = """
A: immutable(uint256)
B: immutable(uint256[10])

@deploy
def __init__(target: address):
    raw_call(target, msg.data)
    A = 1
    B = empty(uint256[10])
"""

CODE_NO_IMMUTABLES = """
@deploy
def __init__(target: address):
    raw_call(target, msg.data)
"""

IMMUTABLES_LEN = 11 * 32  # A + B


def _compile(source):
    settings = Settings(experimental_codegen=True)
    out = compile_code(source, settings=settings, output_formats=["ir", "asm"])
    return str(out["ir"]), out["asm"]


def test_ctor_msize_guard_in_deploy_ir():
    deploy_ir, _ = _compile(CODE_WITH_IMMUTABLES)

    # the deploy IR must contain the memtop (msize) allocation for
    # raw_call(msg.data), with an istore guard touching the immutables
    # region before it. (all immutable assignments come after the
    # raw_call, so the only istore before memtop is the guard.)
    assert "memtop" in deploy_ir
    assert "istore" in deploy_ir
    assert deploy_ir.index("istore") < deploy_ir.index("memtop")


def test_ctor_msize_guard_in_asm():
    _, asm = _compile(CODE_WITH_IMMUTABLES)

    # the guard mstores to the last word of the immutables region
    # (IMMUTABLES_LEN - 32 = 320 = 0x140) before MSIZE is used for
    # dynamic allocation
    guard_ofst = f"0x{IMMUTABLES_LEN - 32:04x}"
    assert f"PUSH2 {guard_ofst}" in asm
    assert asm.index(f"PUSH2 {guard_ofst}") < asm.index("MSIZE")
    assert asm.index("MSTORE") < asm.index("MSIZE")


def test_no_ctor_msize_guard_without_immutables():
    deploy_ir, asm = _compile(CODE_NO_IMMUTABLES)

    # no immutables -> no staging region to protect -> no guard
    assert "memtop" in deploy_ir
    assert "istore" not in deploy_ir
    # nothing writes memory before the dynamic allocation
    assert "MSTORE" not in asm[: asm.index("MSIZE")]
