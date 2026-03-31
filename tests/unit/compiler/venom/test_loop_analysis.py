from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.loop import LoopAnalysis
from vyper.venom.basicblock import IRVariable


def test_simple_loop():
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @body, @exit
    body:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    assert len(analysis.loops) == 1
    loop = analysis.loops[0]

    header = fn.get_basic_block("header")
    body = fn.get_basic_block("body")
    exit_bb = fn.get_basic_block("exit")

    assert loop.header == header
    assert header in loop.body
    assert body in loop.body
    assert exit_bb not in loop.body


def test_no_loops():
    pre = """
    _global:
        jmp @a
    a:
        jmp @b
    b:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    assert len(analysis.loops) == 0
    assert len(analysis.back_edges) == 0


def test_nested_loops():
    pre = """
    _global:
        jmp @outer_header
    outer_header:
        jnz 1, @inner_header, @exit
    inner_header:
        jnz 1, @inner_body, @outer_body
    inner_body:
        jmp @inner_header
    outer_body:
        jmp @outer_header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    assert len(analysis.loops) == 2

    outer_header = fn.get_basic_block("outer_header")
    inner_header = fn.get_basic_block("inner_header")
    inner_body = fn.get_basic_block("inner_body")
    outer_body = fn.get_basic_block("outer_body")
    exit_bb = fn.get_basic_block("exit")

    inner_loop = next(lp for lp in analysis.loops if lp.header == inner_header)
    outer_loop = next(lp for lp in analysis.loops if lp.header == outer_header)

    # inner loop
    assert inner_header in inner_loop.body
    assert inner_body in inner_loop.body
    assert outer_header not in inner_loop.body

    # outer loop contains inner
    assert outer_header in outer_loop.body
    assert inner_header in outer_loop.body
    assert inner_body in outer_loop.body
    assert outer_body in outer_loop.body
    assert exit_bb not in outer_loop.body


def test_exit_nodes():
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @body, @exit
    body:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]
    exit_nodes = analysis.get_exit_nodes(loop)

    exit_bb = fn.get_basic_block("exit")
    assert exit_bb in exit_nodes
    assert len(exit_nodes) == 1


def test_multiple_exit_nodes():
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @body, @exit1
    body:
        jnz 1, @header, @exit2
    exit1:
        stop
    exit2:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]
    exit_nodes = analysis.get_exit_nodes(loop)

    exit1 = fn.get_basic_block("exit1")
    exit2 = fn.get_basic_block("exit2")
    assert exit1 in exit_nodes
    assert exit2 in exit_nodes
    assert len(exit_nodes) == 2


def test_preheader_exists():
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @body, @exit
    body:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]
    preheader = analysis.get_preheader(loop)

    # _global is the single outside predecessor
    assert preheader == fn.get_basic_block("_global")


def test_preheader_none_multiple_entries():
    pre = """
    _global:
        jnz 1, @header, @other
    other:
        jmp @header
    header:
        jnz 1, @body, @exit
    body:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]
    preheader = analysis.get_preheader(loop)

    # multiple outside predecessors, no single preheader
    assert preheader is None


def test_self_loop():
    """Single block that jumps to itself"""
    pre = """
    _global:
        jmp @loop
    loop:
        jnz 1, @loop, @exit
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    assert len(analysis.loops) == 1
    loop = analysis.loops[0]

    loop_bb = fn.get_basic_block("loop")
    assert loop.header == loop_bb
    assert loop_bb in loop.body
    assert len(loop.body) == 1
    assert loop_bb in loop.back_edge_sources


def test_back_edges_property():
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @body, @exit
    body:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]
    header = fn.get_basic_block("header")
    body = fn.get_basic_block("body")

    assert loop.back_edges == [(body, header)]


def test_multiple_back_edges_same_header():
    """Two blocks jump back to same header"""
    pre = """
    _global:
        jmp @header
    header:
        jnz 1, @path1, @exit
    path1:
        jnz 1, @header, @path2
    path2:
        jmp @header
    exit:
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    # should be ONE loop with multiple back edge sources
    assert len(analysis.loops) == 1
    loop = analysis.loops[0]

    header = fn.get_basic_block("header")
    path1 = fn.get_basic_block("path1")
    path2 = fn.get_basic_block("path2")

    assert loop.header == header
    assert path1 in loop.back_edge_sources
    assert path2 in loop.back_edge_sources
    assert header in loop.body
    assert path1 in loop.body
    assert path2 in loop.body


def test_is_variable_defined_in_loop():
    pre = """
    _global:
        %outside = add 1, 2
        jmp @header
    header:
        %header_var = add 3, 4
        jnz 1, @body, @exit
    body:
        %inside = add %outside, %header_var
        jmp @header
    exit:
        %after = add %inside, 1
        stop
    """
    ctx = parse_from_basic_block(pre)
    fn = next(iter(ctx.functions.values()))

    ac = IRAnalysesCache(fn)
    analysis = ac.request_analysis(LoopAnalysis)

    loop = analysis.loops[0]

    outside = IRVariable("%outside")
    header_var = IRVariable("%header_var")
    inside = IRVariable("%inside")
    after = IRVariable("%after")

    assert not analysis.is_variable_defined_in_loop(outside, loop)
    assert analysis.is_variable_defined_in_loop(header_var, loop)
    assert analysis.is_variable_defined_in_loop(inside, loop)
    assert not analysis.is_variable_defined_in_loop(after, loop)
