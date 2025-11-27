from tests.venom_utils import parse_venom
from vyper.venom.basicblock import IRInstruction


def _make_src(a: int, b: int) -> str:
    return f"""
function main {{
main:
    %x, %y = invoke @f
    sink %x, %y
}}

function f {{
f:
    %retpc = param
    %v0 = assign {a}
    %v1 = assign {b}
    ret %v0, %v1, %retpc
}}
"""


def test_parse_multi_output_invoke_builds_two_outputs():
    src = _make_src(7, 9)
    ctx = parse_venom(src)
    fn = ctx.get_function(next(iter(ctx.functions.keys())))
    main_bb = fn.get_basic_block("main")
    inst = next(inst for inst in main_bb.instructions if inst.opcode == "invoke")
    assert isinstance(inst, IRInstruction)
    outs = inst.get_outputs()
    assert len(outs) == 2
