import pytest

from vyper.cli.vyper_compile import compile_files
from vyper.exceptions import VyperException


class VyperFile(pytest.File):
    def collect(self):
        filepath = str(self.fspath)
        yield VyperTestItem.from_parent(self, name=filepath)


class VyperTestItem(pytest.Item):
    def __init__(self, name, parent):
        super().__init__(name, parent)
        self.test_condition = self.name[:-3].split("_")[-1]

    def runtest(self):
        try:

            compile_files(
                [self.fspath],
                ("bytecode",),
            )
            self.test_result = "Success"

        except VyperException as v:
            self.test_result = v.__class__.__name__

        except Exception:
            self.test_result = "Fail"

        if self.test_condition != self.test_result:
            raise VyperTestException(self, self.name)

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, VyperTestException):
            return (
                f"Test failed : {self.name}\n"
                f"Expected: {self.test_condition}\n"
                f"Actual: {self.test_result}\n"
            )

    def reportinfo(self):
        return self.fspath, 0, f"Vyper test file: {self.name}"


class VyperTestException(Exception):
    pass
