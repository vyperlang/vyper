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
    Test that DFT pass does not reorder writes despite dataflow analysis.

    The dataflow graph would allow reordering since %y doesn't depend on
    the first store, but effects dependencies require preserving write order.
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

    The dataflow suggests we could move the store earlier (right after %sum),
    but the effects graph requires it to come after both reads.
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


def test_write_after_multiple_reads_interleaved():
    """
    Test with interleaved reads and writes to different locations.

    The dataflow might suggest reordering, but effects must be preserved.
    """
    source = """
    function test {
        test:
            %loc0 = 0
            %loc4 = 4
            %val = 100

            %read1 = mload %loc0     ; read from location 0
            mstore %loc4, %val       ; write to location 4 (different)
            %read2 = mload %loc0     ; read from location 0 again
            %sum = add %read1, %read2
            %read3 = mload %loc4     ; read from location 4
            mstore %loc0, %sum       ; write to location 0 (after multiple reads)
            %result = add %sum, %read3
            return %result, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find indices
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
    # In internal representation: mstore has [value, location]
    # So we check operands[1] for the location (which is %loc0)
    store0_idx = next(
        i
        for i, inst in enumerate(instructions)
        if inst.opcode == "mstore" and inst.operands[1].name == "%loc0"
    )

    assert store0_idx > read1_idx, "Store to location 0 should come after first read"
    assert store0_idx > read2_idx, "Store to location 0 should come after second read"


def test_array_swap_pattern():
    """
    Test the array swap pattern that originally exposed the bug.

    Multiple reads of array elements before swapping them.
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


def test_accumulating_reads():
    """
    Test pattern with accumulating reads (simulating unrolled loop).

    The dataflow allows early scheduling of the store, but effects require
    it to come after all reads.
    """
    source = """
    function test {
        test:
            %loc = 0
            %one = 1

            ; iteration 1
            %read1 = mload %loc
            %acc1 = add %read1, %one

            ; iteration 2
            %read2 = mload %loc
            %acc2 = add %acc1, %read2

            ; iteration 3
            %read3 = mload %loc
            %acc3 = add %acc2, %read3

            ; this operation suggests store could be moved earlier
            %unrelated = mul %acc3, 100

            ; write back - must come after all reads
            mstore %loc, %acc3

            %final = add %acc3, %unrelated
            return %final, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find all reads and the store
    read_indices = []
    for i, inst in enumerate(instructions):
        if inst.opcode == "mload" and inst.output.name in ["%read1", "%read2", "%read3"]:
            read_indices.append(i)

    store_idx = next(i for i, inst in enumerate(instructions) if inst.opcode == "mstore")

    # Store must come after all reads
    for read_idx in read_indices:
        assert store_idx > read_idx, f"Store should come after read at {read_idx}"


# Now update the write-after-write test to show dataflow vs effects discrepancy
def test_write_after_write_with_dataflow_discrepancy():
    """
    Test write-after-write where dataflow suggests different ordering than effects.

    The dataflow graph would allow reordering since %y doesn't depend on the first store,
    but the effects graph requires preserving the write order.
    """
    source = """
    function test {
        test:
            %x = param
            %y = param
            %loc = 0

            ; first write
            mstore %loc, %x

            ; operations that use %y but not the stored value
            ; dataflow suggests these could be moved before the first store
            %doubled_y = mul %y, 2
            %shifted_y = shl %doubled_y, 1

            ; second write that overwrites the first
            ; dataflow allows this to move up (since it doesn't depend on %x)
            ; but effects require it to stay after the first write
            mstore %loc, %shifted_y

            return %shifted_y, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    # Find both stores to location 0
    store_indices = []
    for i, inst in enumerate(instructions):
        if inst.opcode == "mstore":
            store_indices.append(i)

    assert len(store_indices) == 2
    assert store_indices[0] < store_indices[1], "Write order must be preserved despite dataflow"


@pytest.mark.parametrize(
    "store_op,terminator", [("sstore", "stop"), ("mstore", "return 0, 32"), ("tstore", "stop")]
)
def test_write_after_write_complex_dataflow(store_op, terminator):
    """
    Enhanced write-after-write test showing dataflow vs effects scheduling conflict.

    The intermediate computations create a dataflow that would allow reordering,
    but effects dependencies must preserve write order.
    """
    source = f"""
    function test {{
        test:
            %x = param
            %y = param
            %z = param

            ; first write
            {store_op} 0, %x

            ; complex computation with %y and %z that doesn't depend on the store
            ; dataflow analysis might suggest moving these (and the second store) earlier
            %temp1 = add %y, %z
            %temp2 = mul %temp1, 2
            %temp3 = sub %temp2, %z

            ; second write to different location
            {store_op} 1, %temp1

            ; more computation
            %temp4 = xor %temp3, %y

            ; third write that overwrites the first
            ; dataflow would allow this to move up since it doesn't depend on %x
            ; but effects require it to stay after the first write
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
