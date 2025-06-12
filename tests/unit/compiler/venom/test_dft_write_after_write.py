import pytest

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.parser import parse_venom
from vyper.venom.passes import DFTPass


@pytest.mark.parametrize(
    "store_op,terminator",
    [
        ("sstore", "stop"),  # storage
        ("mstore", "return 0, 32"),  # memory
        ("tstore", "stop"),  # transient storage
    ],
)
def test_write_after_write_dependency(store_op, terminator):
    """
    Test that DFT pass does not reorder writes
    """
    source = f"""
    function test {{
        test:
            %x = param
            %y = param
            {store_op} 0, %x       ; first write
            {store_op} 1, %y       ; second write to different slot
            {store_op} 0, %y       ; third write overwrites first
            {terminator}
    }}
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # find indices of store instructions to slot/location 0
    store0_indices = []

    for i, inst in enumerate(instructions):
        if inst.opcode == store_op and inst.operands[1].value == 0:
            store0_indices.append(i)

    assert len(store0_indices) == 2
    assert store0_indices[0] < store0_indices[1], f"Write order must be preserved for {store_op}"
