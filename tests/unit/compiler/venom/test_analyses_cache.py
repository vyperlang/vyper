from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.fcg import FCGGlobalAnalysis
from vyper.venom.basicblock import IRLabel

SRC = """
function entry {
entry:
    %1 = invoke @f
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
        assert fn in global_cache.function_analyses_caches


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
