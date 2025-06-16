import pytest

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.parser import parse_venom
from vyper.venom.passes import DFTPass


@pytest.mark.parametrize(
    "store_op,terminator",
    [
        ("sstore", "stop"),
        ("mstore", "return 0, 32"),
        ("tstore", "stop"),
    ],
)
def test_write_after_write_dependency(store_op, terminator):
    """
    Test that DFT pass preserves write-after-write ordering despite dataflow.

    The dataflow graph would allow reordering since the second write doesn't
    depend on the first, but effects dependencies require preserving write order.
    """
    source = f"""
    function test {{
        test:
            %x = param
            %y = param

            ; first write to location 0
            {store_op} 0, %x

            ; operations on %y that don't depend on the stored value
            ; dataflow analysis might suggest these could move before the first store
            %y2 = mul %y, 2
            %y3 = add %y2, 1

            ; second write to different location
            {store_op} 1, %y2

            ; third write that overwrites location 0
            ; dataflow would allow moving this earlier (no dependency on %x)
            ; but effects require it to come after the first write
            {store_op} 0, %y3

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


def test_write_after_multiple_reads_simple():
    """
    Test that a write depends on ALL previous reads, not just the last one.
    """
    source = """
    function test {
        test:
            %ptr = 0
            %read1 = mload %ptr      ; first read from location 0
            %read2 = mload %ptr      ; second read from location 0
            %sum = add %read1, %read2
            %doubled = mul %sum, 2   ; dataflow suggests store could go before this
            mstore %ptr, %sum        ; write must come after both reads
            return %doubled, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find instruction indices
    read1_idx = next(
        i
        for i, inst in enumerate(instructions)
        if inst.opcode == "mload" and inst.output.name == "%read1"
    )
    read2_idx = next(
        i
        for i, inst in enumerate(instructions)
        if inst.opcode == "mload" and inst.output.name == "%read2"
    )
    store_idx = next(i for i, inst in enumerate(instructions) if inst.opcode == "mstore")

    assert store_idx > read1_idx, "Store should come after first read"
    assert store_idx > read2_idx, "Store should come after second read"


def test_array_swap_pattern():
    """
    This tests the real-world pattern where bubble sort reads two array
    elements and then swaps them if needed. Both stores must come after
    both reads to avoid corrupting the data.
    """
    source = """
    function test {
        test:
            %base = 1000            ; array base address
            %idx0 = mul 0, 32       ; index 0 * 32
            %idx1 = mul 1, 32       ; index 1 * 32
            %addr0 = add %base, %idx0
            %addr1 = add %base, %idx1

            %elem0 = mload %addr0   ; read arr[0]
            %elem1 = mload %addr1   ; read arr[1]

            %cmp = gt %elem0, %elem1

            ; swap - both stores should come after both reads
            mstore %addr0, %elem1   ; arr[0] = elem1
            mstore %addr1, %elem0   ; arr[1] = elem0

            return %cmp, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find indices
    elem0_idx = next(
        i
        for i, inst in enumerate(instructions)
        if inst.opcode == "mload" and inst.output.name == "%elem0"
    )
    elem1_idx = next(
        i
        for i, inst in enumerate(instructions)
        if inst.opcode == "mload" and inst.output.name == "%elem1"
    )

    # Find both stores
    store_indices = [i for i, inst in enumerate(instructions) if inst.opcode == "mstore"]
    assert len(store_indices) == 2

    # Both stores should come after both reads
    for store_idx in store_indices:
        assert store_idx > elem0_idx, f"Store at {store_idx} should come after read of elem0"
        assert store_idx > elem1_idx, f"Store at {store_idx} should come after read of elem1"


@pytest.mark.parametrize(
    "store_op,terminator", [("sstore", "stop"), ("mstore", "return 0, 32"), ("tstore", "stop")]
)
def test_complex_dataflow_with_effects(store_op, terminator):
    """
    Test complex dataflow patterns where effects override dataflow scheduling.

    This parametrized test ensures the behavior is consistent across all
    storage types (storage, memory, transient).
    """
    source = f"""
    function test {{
        test:
            %x = param
            %y = param
            %z = param

            ; first write
            {store_op} 0, %x

            ; complex computation that doesn't depend on the store
            ; dataflow analysis might suggest moving these earlier
            %temp1 = add %y, %z
            %temp2 = mul %temp1, 2
            %temp3 = sub %temp2, %z

            ; write to different location
            {store_op} 1, %temp1

            ; more computation
            %temp4 = xor %temp3, %y

            ; overwrite location 0 - must stay after first write
            {store_op} 0, %temp4

            {terminator}
    }}
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find stores to location 0
    store0_indices = []
    for i, inst in enumerate(instructions):
        if inst.opcode == store_op and inst.operands[1].value == 0:
            store0_indices.append(i)

    assert len(store0_indices) == 2
    assert store0_indices[0] < store0_indices[1], f"Write order must be preserved for {store_op}"
