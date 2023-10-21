import contextlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Optional

from vyper.exceptions import CompilerPanic, JSONError


# stub
class CompilerInput:
    # an input to the compiler.
    pass


# stub
@dataclass
class VyFile(CompilerInput):
    path: Path
    source_code: str


# stub
@dataclass
class ABIInput(CompilerInput):
    # some json file, either regular ABI or ethPM manifest v3 (EIP-2687)
    path: Path
    abi: Any


class _NotFound(Exception):
    pass


@dataclass
class InputBundle:
    search_paths: list[Path]
    # compilation_targets: dict[str, str]  # contract names => contract sources

    def _load_from_path(self, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._load_from_path()")

    def load_file(self, path: Path) -> str:
        for p in self.search_paths:
            # note from pathlib docs:
            # > If the argument is an absolute path, the previous path is ignored.
            # Path("/a") / Path("/b") => Path("/b")
            to_try = p / path
            try:
                return self._load_from_path(to_try)
            except _NotFound:
                pass
        else:
            formatted_search_paths = "\n".join(["  " + str(sp) for sp in self.search_paths])
            raise FileNotFoundError(
                f"could not find {path} within any of the following search "
                f"paths:\n{formatted_search_paths}"
            )

        raise CompilerPanic("unreachable")  # pragma: nocover

    def add_search_path(self, path) -> None:
        self.search_paths.append(path)

    # temporarily add something to the search path (within the
    # scope of the context manager). if `path` is None, do nothing
    @contextlib.contextmanager
    def search_path(self, path: Optional[Path]) -> None:
        if path is None:
            yield

        else:
            self.search_paths.append(path)
            try:
                yield
            finally:
                self.search_paths.pop()


# regular input. takes a search path(s), and `load_file()` will search all
# search paths for the file and read it from the filesystem
@dataclass
class FilesystemInputBundle(InputBundle):
    def _load_from_path(self, path: Path) -> CompilerInput:
        try:
            with path.open() as f:
                code = f.read()
                return VyFile(path, code)
        except FileNotFoundError:
            raise _NotFound(path)


# fake filesystem for JSON inputs. takes a base path, and `load_file()`
# "reads" the file from the JSON input
@dataclass
class JSONInputBundle(InputBundle):
    input_json: dict[PurePath, Any]

    def _load_from_path(self, path: PurePath) -> CompilerInput:
        try:
            contents = self.input_json[path]
        except KeyError:
            raise _NotFound(path)

        if "abi" in contents:
            return ABIInput(path, contents["abi"])

        if isinstance(contents, list):
            return ABIInput(contents)

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        raise JSONError(f"Unexpected type in file: '{path}'")
