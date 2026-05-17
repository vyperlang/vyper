from tests.venom_utils import parse_venom
from vyper.venom.analysis import CFGAnalysis, IRAnalysesCache
from vyper.venom.check_venom import check_venom_ctx
from vyper.venom.passes import CFGNormalization, MakeSSA


def test_multi_entry_block_1():
    venom_src = """
    function __global {
    __global:
        %op = 10
        %acc = add %op, %op
        jnz %acc, @finish, @block_1

    block_1:
        %acc:1 = add %acc, %op
        %op:1 = 10
        mstore %acc:1, %op:1
        jnz %acc:1, @finish, @target

    target:
        %acc:2 = mul %acc:1, %acc:1
        jmp @finish

    finish:
        stop
    }
    """

    ctx = parse_venom(venom_src)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized(), "CFG should not be normalized"

    CFGNormalization(ac, fn).run_pass()

    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized(), "CFG should be normalized"

    # verify the normalized IR is semantically valid
    check_venom_ctx(ctx)

    finish_bb = fn.get_basic_block("finish")
    cfg_in = list(cfg.cfg_in(finish_bb))
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"


def test_multi_entry_block_2():
    # more complex cfg structure
    venom_src = """
    function __global {
    __global:
        %op = 10
        %acc = add %op, %op
        jnz %acc, @finish, @block_1

    block_1:
        %acc:1 = add %acc, %op
        %op:1 = 10
        mstore %acc:1, %op:1
        jnz %acc:1, @target, @finish

    target:
        %acc:3 = mul %acc:1, %acc:1
        jmp @finish

    finish:
        stop
    }
    """

    ctx = parse_venom(venom_src)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized(), "CFG should not be normalized"

    CFGNormalization(ac, fn).run_pass()

    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized(), "CFG should be normalized"

    # verify the normalized IR is semantically valid
    check_venom_ctx(ctx)

    finish_bb = fn.get_basic_block("finish")
    cfg_in = list(cfg.cfg_in(finish_bb))
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"


def test_multi_entry_block_with_dynamic_jump():
    venom_src = """
    function __global {
    __global:
        %op = 10
        %acc = add %op, %op
        djmp %acc, @finish, @block_1

    block_1:
        %acc:1 = add %acc, %op
        %op:1 = 10
        mstore %acc:1, %op:1
        jnz %acc:1, @finish, @target

    target:
        %acc:2 = mul %acc:1, %acc:1
        jmp @finish

    finish:
        stop
    }
    """

    ctx = parse_venom(venom_src)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized(), "CFG should not be normalized"

    CFGNormalization(ac, fn).run_pass()

    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized(), "CFG should be normalized"

    # verify the normalized IR is semantically valid
    check_venom_ctx(ctx)

    finish_bb = fn.get_basic_block("finish")
    cfg_in = list(cfg.cfg_in(finish_bb))
    assert cfg_in[0].label.value == "target", "Should contain target"
    assert cfg_in[1].label.value == "__global_split_finish", "Should contain __global_split_finish"
    assert cfg_in[2].label.value == "block_1_split_finish", "Should contain block_1_split_finish"


def test_cfg_normalization_with_phi():
    """
    Test that CFG normalization with phi nodes produces semantically valid IR.
    All variables should have reaching definitions after normalization.
    """
    # function in non-ssa form that will need normalization
    venom_src = """
    function test_phi {
    entry:
        %counter = 10
        %x = 1
        jnz %x, @loop_header, @exit

    loop_header:
        %cond = lt %counter, 100
        jnz %cond, @loop_body, @exit

    loop_body:
        %counter = add %counter, 1
        %should_continue = lt %counter, 50
        ; both branches go to blocks
        jnz %should_continue, @loop_header, @exit

    exit:
        return %counter
    }
    """

    ctx = parse_venom(venom_src)
    # functions are keyed by IRLabel
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    # first run makeSSA to convert to SSA form
    MakeSSA(ac, fn).run_pass()

    # check that normalization is needed
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized()

    CFGNormalization(ac, fn).run_pass()

    # check that the cfg is now normalized
    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized()

    # ensures all variables have reaching definitions
    check_venom_ctx(ctx)

    # check that split blocks were created
    split_blocks = [bb for bb in fn.get_basic_blocks() if "split" in bb.label.value]
    assert len(split_blocks) > 0, "Normalization should create split blocks"


def test_phi_forwarding():
    """
    Test a case where phi variable forwarding is required.
    The variable comes from a dominating block and needs to be
    forwarded through split blocks.
    """
    venom_src = """
    function test_forwarding {
    entry:
        %base = 42
        %flag = 1
        jnz %flag, @branch_a, @branch_b

    branch_a:
        %a_val = add %base, 10
        jnz %a_val, @merge, @alternate

    branch_b:
        %b_val = add %base, 20
        jnz %b_val, @merge, @alternate

    merge:
        ; phi references %base which comes from the dominating entry block
        %result = phi @branch_a, %base, @branch_b, %base
        %cond = lt %result, 100
        jmp @exit

    alternate:
        %alt_result = phi @branch_a, %a_val, @branch_b, %b_val
        jmp @exit

    exit:
        %final = phi @merge, %result, @alternate, %alt_result
        return %final
    }
    """

    ctx = parse_venom(venom_src)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    # check that normalization is needed
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized()

    CFGNormalization(ac, fn).run_pass()

    # check that the cfg is now normalized
    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized()

    # ensures all variables have reaching definitions
    check_venom_ctx(ctx)


def test_complex_phi_dependencies():
    """
    Test a more complex case with multiple phi nodes that depend on each other.
    """
    venom_src = """
    function complex_phi {
    entry:
        %a = 1
        %b = 2
        jmp @loop

    loop:
        %x = phi @entry, %a, @body, %y
        %y = phi @entry, %b, @body, %x_next
        %cond = lt %x, 10
        jnz %cond, @body, @exit

    body:
        %x_next = add %x, %y
        %should_exit = gt %x_next, 20
        jnz %should_exit, @exit, @loop

    exit:
        %final = add %x, %y
        return %final
    }
    """

    ctx = parse_venom(venom_src)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)

    # check that normalization is needed
    cfg = ac.request_analysis(CFGAnalysis)
    assert not cfg.is_normalized()

    CFGNormalization(ac, fn).run_pass()

    # check that the cfg is now normalized
    cfg = ac.request_analysis(CFGAnalysis)
    assert cfg.is_normalized()

    # ensures all variables have reaching definitions
    check_venom_ctx(ctx)

    # check that the function has the expected blocks
    block_names = [bb.label.value for bb in fn.get_basic_blocks()]
    assert "entry" in block_names
    assert "loop" in block_names
    assert "body" in block_names
    assert "exit" in block_names
    # and some split blocks
    assert any("split" in name for name in block_names)
