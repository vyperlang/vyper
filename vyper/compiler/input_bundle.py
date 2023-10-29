import contextlib
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Optional

from vyper.exceptions import CompilerPanic, JSONError


class CompilerInput:
    # an input to the compiler.
    pass


@dataclass
class FileInput(CompilerInput):
    source_id: int
    path: Path
    source_code: str


@dataclass
class ABIInput(CompilerInput):
    # some json input, that has already been parsed into a dict or list
    source_id: int
    path: Path
    abi: Any  # something that json.load() returns


class _NotFound(Exception):
    pass


@dataclass
class InputBundle:
    search_paths: list[Path]
    # compilation_targets: dict[str, str]  # contract names => contract sources
    source_id_counter = 0
    source_ids: dict[Path, int] = field(default_factory=dict)

    def _load_from_path(self, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._load_from_path()")

    def _generate_source_id(self, path: Path) -> int:
        if path not in self.source_ids:
            self.source_ids[path] = self.source_id_counter
            self.source_id_counter += 1

        return self.source_ids[path]

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
        except FileNotFoundError:
            raise _NotFound(path)

        source_id = super()._generate_source_id(path)
        return FileInput(source_id, path, code)

# fake filesystem for JSON inputs. takes a base path, and `load_file()`
# "reads" the file from the JSON input. Note that this input bundle type
# never actually interacts with the filesystem -- it is guaranteed to be pure!
@dataclass
class JSONInputBundle(InputBundle):
    input_json: dict[PurePath, Any]

    def _load_from_path(self, path: PurePath) -> CompilerInput:
        try:
            contents = self.input_json[path]
        except KeyError:
            raise _NotFound(path)

        source_id = super()._generate_source_id(path)

        if isinstance(contents, str):
            return FileInput(source_id, path, code)

        if "abi" in contents:
            return ABIInput(source_id, path, contents["abi"])

        if isinstance(contents, list):
            return ABIInput(source_id, path, contents)

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        raise JSONError(f"Unexpected type in file: '{path}'")
