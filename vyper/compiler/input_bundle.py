import contextlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterator, Optional

from vyper.exceptions import CompilerPanic, JSONError

# a type to make mypy happy
PathLike = Path | PurePath


class CompilerInput:
    # an input to the compiler.
    pass


@dataclass
class FileInput(CompilerInput):
    source_id: int
    path: PathLike
    source_code: str


@dataclass
class ABIInput(CompilerInput):
    # some json input, that has already been parsed into a dict or list
    source_id: int
    path: PathLike
    abi: Any  # something that json.load() returns


class _NotFound(Exception):
    pass


class InputBundle:
    search_paths: list[PathLike]
    # compilation_targets: dict[str, str]  # contract names => contract sources

    def __init__(self, search_paths):
        self.search_paths = search_paths
        self._source_id_counter = 0
        self._source_ids: dict[PathLike, int] = {}

    def _load_from_path(self, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._load_from_path()")

    def _generate_source_id(self, path: PathLike) -> int:
        if path not in self._source_ids:
            self._source_ids[path] = self._source_id_counter
            self._source_id_counter += 1

        return self._source_ids[path]

    def load_file(self, path: PathLike) -> CompilerInput:
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

    def add_search_path(self, path: PathLike) -> None:
        self.search_paths.append(path)

    # temporarily add something to the search path (within the
    # scope of the context manager). if `path` is None, do nothing
    @contextlib.contextmanager
    def search_path(self, path: Optional[PathLike]) -> Iterator[None]:
        if path is None:
            yield  # convenience, so caller does not have to handle null path

        else:
            self.search_paths.append(path)
            try:
                yield
            finally:
                self.search_paths.pop()


# regular input. takes a search path(s), and `load_file()` will search all
# search paths for the file and read it from the filesystem
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
class JSONInputBundle(InputBundle):
    input_json: dict[PurePath, Any]

    def __init__(self, search_paths, input_json):
        super().__init__(search_paths)
        self.input_json = input_json

    def _load_from_path(self, path: PurePath) -> CompilerInput:
        try:
            value = self.input_json[path]
        except KeyError:
            raise _NotFound(path)

        source_id = super()._generate_source_id(path)

        if "content" in value:
            return FileInput(source_id, path, value["content"])

        if "abi" in value:
            return ABIInput(source_id, path, value["abi"])

        if isinstance(value, list):
            return ABIInput(source_id, path, value)

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        raise JSONError(f"Unexpected type in file: '{path}'")
