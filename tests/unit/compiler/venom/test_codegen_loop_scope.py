import pytest

from vyper.codegen_venom.stmt import Stmt
from vyper.compiler import compile_code
from vyper.compiler.settings import Settings


@pytest.mark.parametrize("outer", ["range(2)", "[1, 2]"])
@pytest.mark.parametrize("inner", ["range(2)", "[1, 2]"])
def test_loop_variables_leave_codegen_scope(monkeypatch, outer, inner):
    lower_for = Stmt.lower_For
    lowered = []

    def check_scope(stmt):
        variables = stmt.ctx.variables.copy()
        lower_for(stmt)
        # Inner loops must keep the outer counter alive; after either loop,
        # its counter and body locals must no longer be registered.
        assert stmt.ctx.variables == variables
        lowered.append(stmt.node.target.target.id)

    monkeypatch.setattr(Stmt, "lower_For", check_scope)
    code = f"""
@external
def foo() -> uint256:
    total: uint256 = 0
    for i: uint256 in {outer}:
        for j: uint256 in {inner}:
            value: uint256 = i + j
            total += value
        total += i
    for i: uint256 in {outer}:
        total += i
    return total
"""
    compile_code(code, settings=Settings(experimental_codegen=True))
    assert lowered == ["j", "i", "i"]
