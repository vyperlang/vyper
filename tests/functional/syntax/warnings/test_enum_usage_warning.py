import pytest

import vyper


def test_enum_usage_warning():
    code = """
enum Foo:
    Fe
    Fi
    Fo

@external
def foo() -> Foo:
    return Foo.Fe
    """
    with pytest.warns(vyper.warnings.EnumUsage):
        vyper.compile_code(code)
