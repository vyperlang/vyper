import pytest

from vyper.compiler.settings import Settings, VenomOptimizationFlags


@pytest.fixture
def no_inlining_settings(compiler_settings):
    flags = VenomOptimizationFlags(level=compiler_settings.optimize, disable_inlining=True)
    return Settings(**dict(compiler_settings.__dict__, venom_flags=flags))
