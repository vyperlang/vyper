"""
A struct with an unbounded member keeps the member's payload out of line:
the struct holds a 64-byte pointer cell (`[payload_ptr][capacity]`) and the
payload lives in its own buffer. Storing the payload pointer into the cell is
a pointer escape: from then on the payload is reachable only through a
pointer reloaded from memory, which BasePtrAnalysis cannot track. These tests
pin the pass behaviour the layout relies on:

- FmpLoweringPass never reclaims a `dalloca` whose pointer was stored
- ConcretizeMemLocPass never overlaps an `alloca` whose pointer was stored
- DeadStoreElimination keeps the payload stores when the payload is read
  through the reloaded pointer, or handed to a callee / caller
- a payload that is neither stored nor read is dropped and reclaimed (the
  tests above are sensitive to the escape)

The IR mirrors what the frontend emits for a struct constructor with an
unbounded member followed by a member read.
"""

from tests.venom_utils import parse_from_basic_block, run_ssa
from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import BasePtrAnalysis, IRAnalysesCache, MemLivenessAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_location import Allocation
from vyper.venom.parser import parse_venom
from vyper.venom.passes import ConcretizeMemLocPass, DretDesugarPass, FmpLoweringPass
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination

PAYLOAD_LENGTH = 1
PAYLOAD_ELEMENT = 7

# payload buffer (a two-word DynArray: length, one element), then a struct
# `alloca 96` = one word member + a pointer cell at offset 32
_BUILD_STRUCT = f"""
        mstore %payload, {PAYLOAD_LENGTH}
        %elem = add %payload, 32
        mstore %elem, {PAYLOAD_ELEMENT}
        %s = alloca 96
        %owner = caller
        mstore %s, %owner
        %cell = add %s, 32
        mstore %cell, %payload
        %cap = add %cell, 32
        mstore %cap, 0
"""

# the frontend copies the constructed struct into the local, then reads the
# member through the local's cell
_READ_THROUGH_COPY = """
        %copy = alloca 96
        mcopy %copy, %s, 96
        %copy_cell = add %copy, 32
        %ptr = mload %copy_cell
        %len = mload %ptr
        %ptr_elem = add %ptr, 32
        %v = mload %ptr_elem
"""


def _insts(fn: IRFunction, opcode: str) -> list[IRInstruction]:
    return [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == opcode
    ]


def _stored_literals(fn: IRFunction) -> set[int]:
    ret = set()
    for inst in _insts(fn, "mstore"):
        val = inst.operands[0]
        if isinstance(val, IRLiteral):
            ret.add(val.value)
    return ret


def _run_dse(fn: IRFunction) -> None:
    DeadStoreElimination(IRAnalysesCache(fn), fn).run_pass(addr_space=MEMORY)


def _lower_fmp(fn: IRFunction) -> None:
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)
    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()


def _restores_to(fn: IRFunction, mark: str) -> list[IRInstruction]:
    # FmpLoweringPass reclaims a dead allocation suffix by assigning the
    # lowest popped mark back into the free memory pointer
    return [inst for inst in _insts(fn, "assign") if inst.operands[0] == IRVariable(mark)]


def _allocation(fn: IRFunction, name: str) -> Allocation:
    inst = next(
        inst
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode in ("alloca", "dalloca") and inst.output == IRVariable(name)
    )
    return Allocation(inst)


def _entry(src: str) -> IRFunction:
    ctx = parse_from_basic_block(src)
    fn = ctx.entry_function
    assert fn is not None
    return fn


def test_cell_store_escapes_payload():
    fn = _entry(f"""
        main:
            %payload = dalloca 64
            {_BUILD_STRUCT}
            {_READ_THROUGH_COPY}
            sink %len, %v
        """)
    base_ptrs = IRAnalysesCache(fn).request_analysis(BasePtrAnalysis)

    escaped = base_ptrs.escaping_allocations()
    assert _allocation(fn, "%payload") in escaped
    # the struct's own pointer is only ever an address operand
    assert _allocation(fn, "%s") not in escaped
    assert _allocation(fn, "%copy") not in escaped


def test_dse_keeps_payload_read_through_cell():
    fn = _entry(f"""
        main:
            %payload = dalloca 64
            {_BUILD_STRUCT}
            {_READ_THROUGH_COPY}
            sink %len, %v
        """)
    _run_dse(fn)

    assert {PAYLOAD_LENGTH, PAYLOAD_ELEMENT} <= _stored_literals(fn)
    # the cell words feed the struct copy the member is read from
    cell_stores = [
        inst for inst in _insts(fn, "mstore") if inst.operands[0] == IRVariable("%payload")
    ]
    assert len(cell_stores) == 1


def test_fmp_lowering_pins_payload_reached_through_cell():
    # %q is allocated after the last SSA use of %payload. Without the escape
    # the payload region would be reclaimed at %q's allocation and %q would
    # overlay the payload that the member read below still dereferences.
    fn = _entry(f"""
        main:
            %payload = dalloca 64
            {_BUILD_STRUCT}
            %q = dalloca 32
            mstore %q, 0xdead
            {_READ_THROUGH_COPY}
            %t = mload %q
            sink %len, %v, %t
        """)
    _lower_fmp(fn)

    assert len(_insts(fn, "dalloca")) == 0
    assert len(_insts(fn, "bump")) == 2
    assert len(_restores_to(fn, "%payload")) == 0


def test_concretize_keeps_static_payload_reached_through_cell():
    # same shape with a fixed-size payload in the static frame: %tmp is
    # allocated after the payload's last SSA use and must not share its slot
    fn = _entry(f"""
        main:
            %payload = alloca 64
            {_BUILD_STRUCT}
            %tmp = alloca 64
            mstore %tmp, 0xdead
            {_READ_THROUGH_COPY}
            %t = mload %tmp
            sink %len, %v, %t
        """)
    ac = IRAnalysesCache(fn)
    mem_liveness = ac.request_analysis(MemLivenessAnalysis)
    assert _allocation(fn, "%payload") in mem_liveness.escaped

    ConcretizeMemLocPass(ac, fn).run_pass()

    positions = {
        alloca.inst.output.name: pos for alloca, pos in fn.ctx.mem_allocator.allocated.items()
    }
    payload_pos, tmp_pos = positions["%payload"], positions["%tmp"]
    assert payload_pos + 64 <= tmp_pos or tmp_pos + 64 <= payload_pos, positions


def test_payload_passed_to_callee_through_cell():
    # the callee sees only the struct; the payload pointer reaches it through
    # the cell. The caller must keep the payload stores and must not reclaim
    # the payload at %q's allocation.
    ctx = parse_venom(f"""
        function main {{
            main:
                %payload = dalloca 64
                {_BUILD_STRUCT}
                %q = dalloca 32
                mstore %q, 0xdead
                %r = invoke @g, %s
                %t = mload %q
                sink %r, %t
        }}
        function g {{
            g:
                %b = param
                %retpc = retpc_param
                %cell = add %b, 32
                %ptr = mload %cell
                %ptr_elem = add %ptr, 32
                %v = mload %ptr_elem
                ret %v, %retpc
        }}
        """)
    main = ctx.entry_function
    assert main is not None
    g = ctx.get_function(next(label for label in ctx.functions if label.value == "g"))

    _run_dse(main)
    assert {PAYLOAD_LENGTH, PAYLOAD_ELEMENT} <= _stored_literals(main)

    # callee first: lowering a caller reads the callee's sealed convention
    _lower_fmp(g)
    _lower_fmp(main)
    assert len(_insts(main, "bump")) == 2
    assert len(_restores_to(main, "%payload")) == 0


def test_payload_returned_from_callee_through_cell():
    # the callee builds the struct and returns it with the payload as a
    # dynamic return pair, sourcing the payload pointer from the cell
    ctx = parse_venom(f"""
        function mk {{
            mk:
                %retpc = retpc_param
                %payload = dalloca 64
                {_BUILD_STRUCT}
                %ptr = mload %cell
                dret 2, %s, 96, %ptr, 64, %retpc
        }}
        """)
    fn = ctx.entry_function
    assert fn is not None

    DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()
    assert len(_insts(fn, "dret")) == 0
    _run_dse(fn)

    assert {PAYLOAD_LENGTH, PAYLOAD_ELEMENT} <= _stored_literals(fn)


def test_unreached_payload_is_dropped_and_reclaimed():
    # negative control for the tests above: neither stored nor read, the
    # payload's stores are dead and its region is reclaimed at %q
    src = """
        main:
            %payload = dalloca 64
            mstore %payload, 1
            %elem = add %payload, 32
            mstore %elem, 7
            %q = dalloca 32
            mstore %q, 0xdead
            %t = mload %q
            sink %t
        """
    fn = _entry(src)
    _run_dse(fn)
    assert not ({PAYLOAD_LENGTH, PAYLOAD_ELEMENT} & _stored_literals(fn))

    fn = _entry(src)
    _lower_fmp(fn)
    assert len(_insts(fn, "bump")) == 2
    assert len(_restores_to(fn, "%payload")) == 1


def test_unreached_static_payload_shares_its_slot():
    # negative control for the concretization test
    fn = _entry("""
        main:
            %payload = alloca 64
            mstore %payload, 1
            %elem = add %payload, 32
            mstore %elem, 7
            %tmp = alloca 64
            mstore %tmp, 0xdead
            %t = mload %tmp
            sink %t
        """)
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()

    positions = {
        alloca.inst.output.name: pos for alloca, pos in fn.ctx.mem_allocator.allocated.items()
    }
    assert positions["%payload"] == positions["%tmp"], positions
