import pytest

from vyper.old_codegen.context import Context
from vyper.old_codegen.types import BaseType


class ContextMock(Context):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_vars = False
        self._size = 0

    def internal_memory_scope(self):
        if not self._mock_vars:
            for i in range(20):
                self._new_variable(f"#mock{i}", BaseType(self._size), self._size, bool(i % 2))
            self._mock_vars = True
        return super().internal_memory_scope()

    @classmethod
    def set_mock_var_size(cls, size):
        cls._size = size * 32


def pytest_addoption(parser):
    parser.addoption("--memorymock", action="store_true", help="Run tests with mock allocated vars")


def pytest_generate_tests(metafunc):
    if "memory_mocker" in metafunc.fixturenames:
        params = range(1, 11, 2) if metafunc.config.getoption("memorymock") else [False]
        metafunc.parametrize("memory_mocker", params, indirect=True)


def pytest_collection_modifyitems(items, config):
    if config.getoption("memorymock"):
        for item in list(items):
            if "memory_mocker" not in item.fixturenames:
                items.remove(item)

        # hacky magic to ensure the correct number of tests is shown in collection report
        config.pluginmanager.get_plugin("terminalreporter")._numcollected = len(items)


@pytest.fixture
def memory_mocker(monkeypatch, request):
    if request.param:
        monkeypatch.setattr("vyper.old_codegen.context.Context", ContextMock)
        ContextMock.set_mock_var_size(request.param)
