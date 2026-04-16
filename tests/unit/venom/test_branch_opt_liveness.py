def test_branch_optimization_liveness_mutation(get_contract):
    """
    Related to GH issue: https://github.com/vyperlang/vyper/issues/4920
    """

    code = """
#pragma version ^0.4.0

@external
def f(a: bool) -> bool:
    self._h()
    return a or a or a

def _h():
    raw_call(self, b"")
    """

    get_contract(code)
