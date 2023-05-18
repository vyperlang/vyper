from vyper.compiler.phases import CompilerData


def test_dead_code_eliminator():
    code = """
s: uint256

@internal
def foo():
    self.s = 1

@internal
def qux():
    self.s = 2

@external
def bar():
    self.foo()

@external
def __init__():
    self.qux()
    """

    c = CompilerData(code, no_optimize=True)
    initcode_asm = [i for i in c.assembly if not isinstance(i, list)]
    runtime_asm = c.assembly_runtime

    foo_label = "_sym_internal_foo___"
    qux_label = "_sym_internal_qux___"

    # all the labels should be in all the unoptimized asms
    for s in (foo_label, qux_label):
        assert s + "_deploy" in initcode_asm
        assert s + "_runtime" in runtime_asm

    c = CompilerData(code, no_optimize=False)
    initcode_asm = [i for i in c.assembly if not isinstance(i, list)]
    runtime_asm = c.assembly_runtime

    # qux should not be in runtime code
    for instr in runtime_asm:
        if isinstance(instr, str):
            assert not instr.startswith(qux_label), instr

    # foo should not be in initcode asm
    for instr in initcode_asm:
        if isinstance(instr, str):
            assert not instr.startswith(foo_label), instr
