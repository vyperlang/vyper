import pytest

from tests.hevm import hevm_check_venom_ctx
from vyper.venom.parser import parse_venom


@pytest.mark.hevm
def test_invoke_two_returns_executes_correctly():
    a, b = 7, 9

    pre = parse_venom(
        f"""
        function main {{
            main:
                %a, %b = invoke @f
                sink %a, %b
        }}

        function f {{
            f:
                %retpc = param
                %v0 = {a}
                %v1 = {b}
                ret %v0, %v1, %retpc
        }}
    """
    )

    post = parse_venom(
        f"""
        function main {{
            main:
                sink {a}, {b}
        }}
    """
    )

    hevm_check_venom_ctx(pre, post)
