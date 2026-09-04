from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.dfg import DFGAnalysis
from vyper.venom.analysis.fcg import FCGGlobalAnalysis
from vyper.venom.basicblock import IRLabel, IRVariable

SRC = """
function entry {
entry:
    invoke @f
    stop
}

function f {
f:
    %retpc = param
    ret %retpc
}
"""


def test_global_cache_creation_registers_self():
    ctx = parse_venom(SRC)
    entry = ctx.get_function(IRLabel("entry"))

    ac = IRAnalysesCache(entry)
    ac.request_analysis(FCGGlobalAnalysis)

    global_cache = ctx.global_analyses_cache
    assert global_cache is not None
    # the cache which requested the global analysis must be the registered one
    assert global_cache.function_analyses_caches[entry] is ac
    # other functions get fresh caches
    for fn in ctx.functions.values():
        if fn is not entry:
            assert global_cache.function_analyses_caches[fn] is not ac


def test_existing_global_cache_registers_self():
    # regression test for https://github.com/vyperlang/vyper/issues/5046
    ctx = parse_venom(SRC)
    entry = ctx.get_function(IRLabel("entry"))
    f = ctx.get_function(IRLabel("f"))

    # first request creates the global cache via the `global_cache is None` path
    ac_entry = IRAnalysesCache(entry)
    ac_entry.request_analysis(FCGGlobalAnalysis)

    # second request from a different function's cache takes the fallback path;
    # it must register itself in the global cache, not a parallel cache
    ac_f = IRAnalysesCache(f)
    ac_f.request_analysis(FCGGlobalAnalysis)

    global_cache = ctx.global_analyses_cache
    assert global_cache is not None
    assert global_cache.function_analyses_caches[f] is ac_f


def test_existing_authoritative_cache_not_displaced():
    # a real (non-placeholder) cache registered for a function must not be
    # displaced by a temporary cache for the same function -- consumers
    # rely on the registered cache's invalidations
    ctx = parse_venom(SRC)
    entry = ctx.get_function(IRLabel("entry"))

    ac_entry = IRAnalysesCache(entry)
    ac_entry.request_analysis(FCGGlobalAnalysis)

    global_cache = ctx.global_analyses_cache
    assert global_cache is not None
    assert global_cache.function_analyses_caches[entry] is ac_entry

    # a second, temporary cache for the same function must defer to the
    # registered one
    ac_tmp = IRAnalysesCache(entry)
    ac_tmp.request_analysis(FCGGlobalAnalysis)
    assert global_cache.function_analyses_caches[entry] is ac_entry


def test_temporary_requester_and_later_consumer_share_invalidations():
    ctx = parse_venom(SRC)
    entry = ctx.get_function(IRLabel("entry"))
    fn = ctx.get_function(IRLabel("f"))
    IRAnalysesCache(entry).request_analysis(FCGGlobalAnalysis)

    temporary = IRAnalysesCache(fn)
    temporary.request_analysis(FCGGlobalAnalysis)
    old = temporary.request_analysis(DFGAnalysis)
    active = IRAnalysesCache(fn)
    assert active.request_analysis(DFGAnalysis) is old

    # Rename the return-PC parameter and its use, then invalidate only through
    # the active consumer. The global consumer must see the updated DFG too.
    replacement = IRVariable("new_retpc")
    fn.entry.instructions[0].set_outputs([replacement])
    fn.entry.instructions[1].operands = [replacement]
    active.invalidate_analysis(DFGAnalysis)

    global_cache = ctx.global_analyses_cache
    assert global_cache is not None
    registered = global_cache.function_analyses_caches[fn]
    fresh = registered.request_analysis(DFGAnalysis)
    assert fresh is not old
    assert fresh is active.request_analysis(DFGAnalysis)
    assert fresh.get_producing_instruction(replacement) is fn.entry.instructions[0]
    assert fresh.get_producing_instruction(IRVariable("retpc")) is None
    forced = active.force_analysis(DFGAnalysis)
    assert forced is not fresh
    assert forced is registered.request_analysis(DFGAnalysis)


def test_used_placeholder_can_be_replaced():
    ctx = parse_venom(SRC)
    entry = ctx.get_function(IRLabel("entry"))
    fn = ctx.get_function(IRLabel("f"))
    IRAnalysesCache(entry).request_analysis(FCGGlobalAnalysis)
    global_cache = ctx.global_analyses_cache
    assert global_cache is not None
    placeholder = global_cache.function_analyses_caches[fn]
    placeholder.request_analysis(DFGAnalysis)

    consumer = IRAnalysesCache(fn)
    consumer.request_analysis(DFGAnalysis)
    assert global_cache.function_analyses_caches[fn] is consumer
    assert placeholder.request_analysis(DFGAnalysis) is consumer.request_analysis(DFGAnalysis)
