from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.passes import (
    DretDesugarPass,
    FmpLoweringPass,
    InternalReturnCopyForwardingPass,
    MakeSSA,
    PhiEliminationPass,
    ReadonlyInvokeArgCopyForwardingPass,
)


def _run_copy_forwarding(src: str, setup=None):
    ctx = parse_venom(src)
    if setup is not None:
        setup(ctx)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    for fn in ctx.functions.values():
        InternalReturnCopyForwardingPass(analyses[fn], fn).run_pass()
        ReadonlyInvokeArgCopyForwardingPass(analyses[fn], fn).run_pass()
    return ctx


def _lower_dalloca(ctx):
    for fn in reversed(list(ctx.functions.values())):
        DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        PhiEliminationPass(ac, fn).run_pass()
        FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        PhiEliminationPass(ac, fn).run_pass()


def test_readonly_forwarding_rejects_src_clobber_before_invoke():
    src = """
    function caller {
    caller:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        mstore %src, 1
        invoke @callee, %tmp
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    # Copy must remain; invoke should still use the staged destination.
    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_still_applies_without_src_clobber():
    src = """
    function caller {
    caller:
        %src = alloca 64
        %tmp = alloca 64
        mcopy %tmp, %src, 64
        invoke @callee, %tmp
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_allows_large_staged_arg_without_expensive_callee_frame():
    src = """
    function caller {
    caller:
        %src = alloca 1056
        %tmp = alloca 1056
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_allows_profitable_liveness_extension():
    src = """
    function caller {
    caller:
        %src = alloca 1088
        %tmp = alloca 1088
        %v = mload %src
        mstore 0, %v
        mcopy %tmp, %src, 1088
        invoke @callee, %tmp
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 1024
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_allows_when_retained_copy_is_not_cheaper():
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 1056
        %tmp = alloca 1056
        %v = mload %src
        mstore 0, %v
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 4096
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_allows_retained_copy_comparison_from_invoke_arg():
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 1056
        %tmp = alloca 1056
        invoke @reader, %src
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    exit:
        stop
    }

    function reader {
    reader:
        %arg = param
        %retpc = param
        mload %arg
        ret %retpc
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 4096
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(
        inst for inst in insts if inst.opcode == "invoke" and inst.operands[0] == IRLabel("callee")
    )

    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_rejects_param_source_with_huge_callee_frame():
    # Source is a function param (unresolved alloca). The callee transitively
    # holds two ABI-encode-scale buffers (totaling >8MB) — after inlining the
    # param could resolve to a small caller alloca that gets forced to a high
    # address by the conflict graph, producing a quadratic memory-expansion
    # gas bomb. Forwarding must bail out.
    src = """
    function caller {
    caller:
        %arg = param
        %retpc = param
        %tmp = alloca 4128
        mcopy %tmp, %arg, 4128
        invoke @callee, %tmp
        ret %retpc
    }

    function callee {
    callee:
        %a = param
        %retpc = param
        %buf1 = alloca 4195552
        %buf2 = alloca 4195424
        mload %a
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_allows_param_source_with_small_callee_frame():
    # Source is a function param but the callee's transitive frame is tiny —
    # any post-inlining placement is cheap, so forwarding wins.
    src = """
    function caller {
    caller:
        %arg = param
        %retpc = param
        %tmp = alloca 1056
        mcopy %tmp, %arg, 1056
        invoke @callee, %tmp
        ret %retpc
    }

    function callee {
    callee:
        %a = param
        %retpc = param
        %frame = alloca 64
        mload %a
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    assert invoke.operands[1] == IRVariable("%arg")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_rejects_param_source_with_unresolvable_callee_frame():
    # Source is a function param (unresolved alloca). The callee has no visible
    # frame of its own, but its transitive frame cannot be resolved: it invokes
    # an unknown target, so the walker cannot bound the frame size. An
    # unresolved frame must NOT be treated as empty (zero-cost) — we cannot rule
    # out a catastrophic post-inlining placement, so forwarding must bail out.
    src = """
    function caller {
    caller:
        %arg = param
        %retpc = param
        %tmp = alloca 1056
        mcopy %tmp, %arg, 1056
        invoke @callee, %tmp
        ret %retpc
    }

    function callee {
    callee:
        %a = param
        %retpc = param
        invoke @unknown_external
        mload %a
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(
        inst for inst in insts if inst.opcode == "invoke" and inst.operands[0] == IRLabel("callee")
    )

    # forwarding blocked: the invoke still consumes the staged copy, not %arg
    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_rejects_resolved_source_with_unresolvable_callee_frame():
    # Source is a resolved static-frame alloca whose write sits on a path that
    # can skip the invoke, so the cost model must weigh liveness extension
    # against the callee's frame. That frame cannot be resolved (the callee
    # invokes an unknown target), and an unresolved frame must NOT be treated
    # as empty (zero-cost) — mirror the unresolved-source path and bail out.
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 1056
        %tmp = alloca 1056
        mstore %src, 1
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        invoke @unknown_external
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(
        inst for inst in insts if inst.opcode == "invoke" and inst.operands[0] == IRLabel("callee")
    )

    # forwarding blocked: the invoke still consumes the staged copy, not %src
    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_rejects_larger_source_liveness_extension():
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 65536
        %tmp = alloca 1056
        %v = mload %src
        mstore 0, %v
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 4096
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_allows_source_liveness_after_invoke():
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 1056
        %tmp = alloca 1056
        %pre = mload %src
        mstore 0, %pre
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        %post = mload %src
        mstore 0, %post
        stop
    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 4096
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_rejects_unprofitable_liveness_extension_from_source_write():
    src = """
    function caller {
    caller:
        %cond = param
        %src = alloca 1056
        %tmp = alloca 1056
        mstore %src, 1
        jnz %cond, @call, @exit
    call:
        mcopy %tmp, %src, 1056
        invoke @callee, %tmp
        stop
    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        %frame = alloca 4096
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(inst for inst in insts if inst.opcode == "invoke")

    assert invoke.operands[1] == mcopy.operands[2]


def test_readonly_forwarding_rejects_same_source_mutable_sibling_arg():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %tmp = alloca 32
        mcopy %tmp, %src, 32
        invoke @callee, %tmp, %src
        stop
    }

    function callee {
    callee:
        %arg_ro = param
        %arg_rw = param
        %retpc = param
        mstore %arg_rw, 1
        %v = mload %arg_ro
        mstore 0, %v
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    # Forwarding arg_ro -> %src would alias it with mutable arg_rw.
    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    invoke_args = list(invoke.operands[1:])
    assert invoke_args.count(IRVariable("%tmp")) == 1
    assert invoke_args.count(IRVariable("%src")) == 1
    assert any(inst.opcode == "mcopy" for inst in insts)


def test_readonly_forwarding_allows_same_source_readonly_sibling_arg():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %tmp = alloca 32
        mcopy %tmp, %src, 32
        invoke @callee, %tmp, %src
        stop
    }

    function callee {
    callee:
        %arg0 = param
        %arg1 = param
        %retpc = param
        %v0 = mload %arg0
        %v1 = mload %arg1
        mstore 0, %v0
        mstore 32, %v1
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    # Both callee args are readonly, so aliasing the two args is safe.
    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    invoke_args = list(invoke.operands[1:])
    assert invoke_args.count(IRVariable("%tmp")) == 0
    assert invoke_args.count(IRVariable("%src")) == 2
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_ignores_hidden_fmp_arg():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %tmp = alloca 32
        %other = alloca 32
        mcopy %tmp, %src, 32
        invoke @callee, %tmp, %other
        stop
    }

    function callee {
    callee:
        %arg_rw = param
        %arg_ro = param
        %retpc = param
        %scratch = dalloca 32
        mstore %arg_rw, 1
        %v = mload %arg_ro
        mstore 0, %v
        ret %retpc
    }
    """

    ctx = parse_venom(src)
    _lower_dalloca(ctx)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    for fn in ctx.functions.values():
        InternalReturnCopyForwardingPass(analyses[fn], fn).run_pass()
        ReadonlyInvokeArgCopyForwardingPass(analyses[fn], fn).run_pass()

    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    assert invoke.operands[1] == IRVariable("%other")
    assert invoke.operands[2] == IRVariable("%src")
    assert all(inst.opcode != "mcopy" for inst in insts)


def test_readonly_forwarding_blocks_dynamic_copy_source():
    src = """
    function caller {
    caller:
        %src = dalloca 32
        %cond = source
        jnz %cond, @write, @copy

    write:
        mstore %src, 1
        %cond2 = source
        jnz %cond2, @copy, @exit

    copy:
        %tmp = alloca 32
        mcopy %tmp, %src, 32
        invoke @callee, %tmp
        stop

    exit:
        stop
    }

    function callee {
    callee:
        %arg = param
        %retpc = param
        mload %arg
        ret %retpc
    }
    """

    ctx = _run_copy_forwarding(src)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    mcopy = next(inst for inst in insts if inst.opcode == "mcopy")
    invoke = next(inst for inst in insts if inst.opcode == "invoke")
    assert invoke.operands[1] == mcopy.operands[2]


def test_internal_return_forwarding_still_applies_without_src_clobber():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %dst = alloca 32
        invoke @callee, %src
        mcopy %dst, %src, 32
        %v = mload %dst
        sink %v
    }

    function callee {
    callee:
        %retbuf = param
        %retpc = param
        mstore %retbuf, 7
        ret %retpc
    }
    """

    def _setup(ctx):
        callee = ctx.get_function(IRLabel("callee"))
        callee._has_memory_return_buffer_param = True

    ctx = _run_copy_forwarding(src, setup=_setup)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    # Forwarding should remove the copy and rewrite the load to source buffer.
    assert all(inst.opcode != "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    assert mload.operands[0] == IRVariable("%src")


def test_internal_return_forwarding_allows_disjoint_intervening_invoke_write():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %dst = alloca 32
        %other = alloca 32
        invoke @producer, %src
        mcopy %dst, %src, 32
        invoke @writer, %other
        %v = mload %dst
        sink %v
    }

    function producer {
    producer:
        %retbuf = param
        %retpc = param
        mstore %retbuf, 7
        ret %retpc
    }

    function writer {
    writer:
        %retbuf = param
        %retpc = param
        mstore %retbuf, 9
        ret %retpc
    }
    """

    def _setup(ctx):
        for fn_name in ("producer", "writer"):
            callee = ctx.get_function(IRLabel(fn_name))
            callee._has_memory_return_buffer_param = True

    ctx = _run_copy_forwarding(src, setup=_setup)
    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    # Intervening invoke writes to a disjoint buffer, so copy can be forwarded.
    assert all(inst.opcode != "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    assert mload.operands[0] == IRVariable("%src")


def test_internal_return_forwarding_ignores_hidden_fmp_arg():
    src = """
    function caller {
    caller:
        %src = alloca 32
        %dst = alloca 32
        invoke @callee, %src
        mcopy %dst, %src, 32
        %v = mload %dst
        sink %v
    }

    function callee {
    callee:
        %retbuf = param
        %retpc = param
        %scratch = dalloca 32
        mstore %retbuf, 7
        ret %retpc
    }
    """

    ctx = parse_venom(src)
    callee = ctx.get_function(IRLabel("callee"))
    callee._has_memory_return_buffer_param = True

    _lower_dalloca(ctx)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    for fn in ctx.functions.values():
        InternalReturnCopyForwardingPass(analyses[fn], fn).run_pass()
        ReadonlyInvokeArgCopyForwardingPass(analyses[fn], fn).run_pass()

    caller = ctx.get_function(IRLabel("caller"))
    insts = [inst for bb in caller.get_basic_blocks() for inst in bb.instructions]

    assert all(inst.opcode != "mcopy" for inst in insts)
    mload = next(inst for inst in insts if inst.opcode == "mload")
    assert mload.operands[0] == IRVariable("%src")
