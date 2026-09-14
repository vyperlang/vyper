from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import MakeSSA
from vyper.venom.passes.mem2var import Mem2Var


def _find_insts(fn, opcode):
    return [
        inst for bb in fn.get_basic_blocks() for inst in bb.instructions if inst.opcode == opcode
    ]


def _run_mem2var(pre: str):
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    Mem2Var(ac, fn).run_pass()
    return fn


def test_mem2var_promotes_simple_alloca():
    """
    A 32-byte alloca whose only uses are mload/mstore address operands
    is promoted to a stack variable.
    """
    pre = """
    main:
        %ptr = alloca 32
        mstore %ptr, 42
        %v = mload %ptr
        sink %v
    """
    fn = _run_mem2var(pre)

    assert len(_find_insts(fn, "mload")) == 0
    assert len(_find_insts(fn, "mstore")) == 0


def test_mem2var_skips_alloca_used_as_stored_value():
    """
    Mem2Var must NOT promote an alloca whose pointer is used as the
    VALUE operand of an mstore (`mstore %b, %a` stores the pointer %a
    into the slot %b) -- the pointer escapes through memory.
    See issue #5070.
    """
    pre = """
    main:
        %a = alloca 32
        %b = source
        mstore %b, %a
        %x = mload %a
        return %b, 32
    """
    fn = _run_mem2var(pre)

    # %a must not be promoted: the store of the pointer must survive
    allocas = _find_insts(fn, "alloca")
    assert len(allocas) == 1, f"alloca should be preserved, got {allocas}"
    mstores = _find_insts(fn, "mstore")
    assert len(mstores) == 1, f"mstore of the pointer must survive, got {mstores}"
    val, _ptr = mstores[0].operands
    assert val == allocas[0].output, f"stored value should be the pointer, got {val}"
    # the load through %a must survive as well
    assert len(_find_insts(fn, "mload")) == 1


def test_mem2var_stored_pointer_dest_promoted_first():
    """
    Same escape shape as above, but the *destination* slot is itself a
    promotable alloca which is visited first. Promoting %b rewrites
    `mstore %b, %a` to `%alloca_b = %a`; that assign use must then block
    promotion of %a, and the pointer-value flow must be preserved.
    """
    pre = """
    main:
        %b = alloca 32
        %a = alloca 32
        mstore %b, %a
        %x = mload %a
        %y = mload %b
        sink %x, %y
    """
    fn = _run_mem2var(pre)

    # the load through %a must remain a real memory load
    # (the dead %b alloca instruction is left for DCE to clean up)
    allocas = _find_insts(fn, "alloca")
    a = next(inst for inst in allocas if inst.output.name.startswith("%a"))
    mloads = _find_insts(fn, "mload")
    assert len(mloads) == 1
    assert mloads[0].operands[0] == a.output

    # %b may be promoted; the pointer value must flow into its
    # replacement variable (an assign of %a)
    assigns = [inst for inst in _find_insts(fn, "assign") if inst.operands[0] == a.output]
    assert len(assigns) == 1
