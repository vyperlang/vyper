import pytest

from tests.hevm import hevm_check_venom_ctx
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction

# Will update when we have a proper support for the parser
def _ctx_with_invoke_two_returns(a: int, b: int) -> IRContext:
    ctx = IRContext()

    # Callee: f
    f = IRFunction(IRLabel("f"), ctx)
    ctx.add_function(f)
    f_entry = f.get_basic_block("f")
    # return_pc param
    retpc = f_entry.append_instruction("param")
    # two constants
    v0 = f_entry.append_instruction("assign", IRLiteral(a))
    v1 = f_entry.append_instruction("assign", IRLiteral(b))
    # ret v0, v1, %retpc
    assert retpc is not None and v0 is not None and v1 is not None
    f_entry.append_instruction("ret", v0, v1, retpc)

    # Caller: main
    main = IRFunction(IRLabel("main"), ctx)
    ctx.add_function(main)
    main_bb = main.get_basic_block("main")
    # Two-output invoke of @f
    outs = main_bb.append_invoke_instruction([IRLabel("f")], returns=2)
    # sink the results
    if isinstance(outs, list):  # returns=2
        main_bb.append_instruction("sink", *outs)
    else:
        main_bb.append_instruction("sink", outs)

    return ctx


def _ctx_sink_constants(a: int, b: int) -> IRContext:
    ctx = IRContext()
    main = IRFunction(IRLabel("main"), ctx)
    ctx.add_function(main)
    bb = main.get_basic_block("main")
    bb.append_instruction("sink", IRLiteral(a), IRLiteral(b))
    return ctx


@pytest.mark.hevm
def test_invoke_two_returns_executes_correctly():
    a, b = 7, 9

    pre = _ctx_with_invoke_two_returns(a, b)
    post = _ctx_sink_constants(a, b)

    hevm_check_venom_ctx(pre, post)

