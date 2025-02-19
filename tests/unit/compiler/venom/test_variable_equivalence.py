import itertools

from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import DFGAnalysis, IRAnalysesCache
from vyper.venom.basicblock import IRVariable
from vyper.venom.context import IRContext


def _entry_fn(ctx: "IRContext"):
    # TODO: make this part of IRContext
    return next(iter(ctx.functions.values()))


def test_variable_equivalence_dfg_order():
    a_code = """
    main:
    %1 = 1
    %2 = %1
    %3 = %2
    """
    # technically invalid code, but variable equivalence should handle
    # it either way
    b_code = """
    main:
    %3 = %2
    %2 = %1
    %1 = 1
    """
    fn1 = _entry_fn(parse_from_basic_block(a_code))
    fn2 = _entry_fn(parse_from_basic_block(b_code))

    dfg1 = IRAnalysesCache(fn1).request_analysis(DFGAnalysis)
    dfg2 = IRAnalysesCache(fn2).request_analysis(DFGAnalysis)

    vars_ = map(IRVariable, ("%1", "%2", "%3"))
    for var1, var2 in itertools.combinations(vars_, 2):
        assert dfg1.are_equivalent(var1, var2)
        assert dfg2.are_equivalent(var1, var2)
