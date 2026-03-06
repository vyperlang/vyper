from vyper.venom.analysis import LivenessAnalysis
from vyper.venom.analysis.liveness_monotone import LivenessMonotoneAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from tests.venom_utils import parse_from_basic_block

def test_basic_compare():
    code = """
    main:
        %1 = source
        %2 = source
        mstore %1, %2
        mstore 100, %2
        ret %1
    """
    
    ctx = parse_from_basic_block(code)
    fn = [fn for fn in ctx.functions.values()][0]

    ac = IRAnalysesCache(fn)
    orig = ac.request_analysis(LivenessAnalysis)
    new = ac.request_analysis(LivenessMonotoneAnalysis)
    
    bb = next(fn.get_basic_blocks())

    for inst in bb.instructions:
        orig_live = orig.live_vars_at(inst)
        new_live = new.live_vars_at(inst)
        assert orig_live == new_live, (inst, orig_live, new_live)

def test_liveness_phi_with_branching():
    """Test liveness with phi in a branching structure."""
    code = """
    main:
        %a = param
        jmp @header
    header:
        %b = phi @main, %a, @body, %b
        %cond = iszero %b
        jmp %cond, @body, @exit
    body:
        %c = add %b, 1
        jmp @header
    exit:
        sink %b
    """
    ctx = parse_from_basic_block(code)
    fn = [fn for fn in ctx.functions.values()][0]

    ac = IRAnalysesCache(fn)
    orig = ac.request_analysis(LivenessAnalysis)
    new = ac.request_analysis(LivenessMonotoneAnalysis)
    
    
    # Check that both analyses give consistent results
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.opcode == "phi":
                orig_live = orig.live_vars_at(inst)
                new_live = new.live_vars_at(inst)
                assert orig_live == new_live, (inst, orig_live, new_live)
                    
