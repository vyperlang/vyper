import contextlib
from dataclasses import dataclass, field
from typing import Iterator

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, ImportCycle

"""
data structure for collecting import statements and validating the
import graph
"""


@dataclass
class ImportGraph:
    # the current path in the import graph traversal
    _path: list[vy_ast.Module] = field(default_factory=list)

    def push_path(self, module_ast: vy_ast.Module) -> None:
        if module_ast in self._path:
            cycle = self._path + [module_ast]
            raise ImportCycle(" imports ".join(f'"{t.path}"' for t in cycle))

        self._path.append(module_ast)

    def pop_path(self, expected: vy_ast.Module) -> None:
        popped = self._path.pop()
        if expected != popped:
            raise CompilerPanic("unreachable")

    @contextlib.contextmanager
    def enter_path(self, module_ast: vy_ast.Module) -> Iterator[None]:
        self.push_path(module_ast)
        try:
            yield
        finally:
            self.pop_path(module_ast)
