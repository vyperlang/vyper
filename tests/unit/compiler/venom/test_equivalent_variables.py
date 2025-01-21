from collections import defaultdict

from tests.venom_utils import parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache, VarEquivalenceAnalysis
from vyper.venom.basicblock import IRLiteral


def _check_expected(code, expected):
    ctx = parse_from_basic_block(code)
    fn = next(iter(ctx.functions.values()))
    ac = IRAnalysesCache(fn)
    eq = ac.request_analysis(VarEquivalenceAnalysis)

    tmp = defaultdict(list)
    for var, bag in eq._bags.items():
        if not isinstance(var, IRLiteral):
            tmp[bag].append(var)

    ret = []
    for varset in tmp.values():
        ret.append(tuple(var.value for var in varset))

    assert tuple(ret) == expected


def test_simple_equivalent_vars():
    code = """
    main:
        %1 = 5
        %2 = %1
    """
    expected = (("%1", "%2"),)
    _check_expected(code, expected)


def test_equivalent_vars2():
    code = """
    main:
        # graph with multiple edges from root: %1 => %2 and %1 => %3
        %1 = 5
        %2 = %1
        %3 = %1
    """
    expected = (("%1", "%2", "%3"),)
    _check_expected(code, expected)


def test_equivalent_vars3():
    code = """
    main:
        # even weirder graph
        %1 = 5
        %2 = %1
        %3 = %2
        %4 = %2
        %5 = %1
        %6 = 7  ; disjoint
    """
    expected = (("%1", "%2", "%3", "%4", "%5"), ("%6",))
    _check_expected(code, expected)


def test_equivalent_vars4():
    code = """
    main:
        # even weirder graph
        %1 = 5
        %2 = %1
        %3 = 5  ; not disjoint, equality on 5
        %4 = %3
    """
    expected = (("%1", "%2", "%3", "%4"),)
    _check_expected(code, expected)


def test_equivalent_vars5():
    """
    Test with non-literal roots
    """
    code = """
    main:
        %1 = param
        %2 = %1
        %3 = param  ; disjoint
        %4 = %3
    """
    expected = (("%1", "%2"), ("%3", "%4"))
    _check_expected(code, expected)
