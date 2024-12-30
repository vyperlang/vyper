import itertools
from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache, VarEquivalenceAnalysis
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

    eq1 = IRAnalysesCache(fn1).request_analysis(VarEquivalenceAnalysis)
    eq2 = IRAnalysesCache(fn2).request_analysis(VarEquivalenceAnalysis)

    vars_ = map(IRVariable, ("%1", "%2", "%3"))
    for var1, var2 in itertools.combinations(vars_, 2):
        assert eq1.equivalent(var1, var2)
        assert eq2.equivalent(var1, var2)

    # doesn't have to pass since it's internal to the class, but extra
    # guarantee of correctness that it does
    assert eq1._equivalence_set == eq2._equivalence_set
