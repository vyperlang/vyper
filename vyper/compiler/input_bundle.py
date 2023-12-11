import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Iterator, Optional

from vyper.exceptions import JSONError

# a type to make mypy happy
PathLike = Path | PurePath


@dataclass
class CompilerInput:
    # an input to the compiler, basically an abstraction for file contents
    source_id: int
    path: PathLike


@dataclass
class FileInput(CompilerInput):
    source_code: str


@dataclass
class ABIInput(CompilerInput):
    # some json input, which has already been parsed into a dict or list
    # this is needed because json inputs present json interfaces as json
    # objects, not as strings. this class helps us avoid round-tripping
    # back to a string to pretend it's a file.
    abi: Any  # something that json.load() returns


def try_parse_abi(file_input: FileInput) -> CompilerInput:
    try:
        s = json.loads(file_input.source_code)
        return ABIInput(file_input.source_id, file_input.path, s)
    except (ValueError, TypeError):
        return file_input


class _NotFound(Exception):
    pass


# wrap os.path.normpath, but return the same type as the input
def _normpath(path):
    return path.__class__(os.path.normpath(path))


# an "input bundle" to the compiler, representing the files which are
# available to the compiler. it is useful because it parametrizes I/O
# operations over different possible input types. you can think of it
# as a virtual filesystem which models the compiler's interactions
# with the outside world. it exposes a "load_file" operation which
# searches for a file from a set of search paths, and also provides
# id generation service to get a unique source id per file.
class InputBundle:
    # a list of search paths
    search_paths: list[PathLike]

    _cache: Any

    def __init__(self, search_paths):
        self.search_paths = search_paths
        self._source_id_counter = 0
        self._source_ids: dict[PathLike, int] = {}

        # this is a little bit cursed, but it allows consumers to cache data that
        # share the same lifetime as this input bundle.
        self._cache = lambda: None

    def _load_from_path(self, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._load_from_path()")

    def _generate_source_id(self, path: PathLike) -> int:
        # Note: it is possible for a file to get in here more than once,
        # e.g. by symlink
        if path not in self._source_ids:
            self._source_ids[path] = self._source_id_counter
            self._source_id_counter += 1

        return self._source_ids[path]

    def load_file(self, path: PathLike | str) -> CompilerInput:
        # search path precedence
        tried = []
        for sp in reversed(self.search_paths):
            # note from pathlib docs:
            # > If the argument is an absolute path, the previous path is ignored.
            # Path("/a") / Path("/b") => Path("/b")
            to_try = sp / path

            # normalize the path with os.path.normpath, to break down
            # things like "foo/bar/../x.vy" => "foo/x.vy", with all
            # the caveats around symlinks that os.path.normpath comes with.
            to_try = _normpath(to_try)
            try:
                res = self._load_from_path(to_try)
                break
            except _NotFound:
                tried.append(to_try)

        else:
            formatted_search_paths = "\n".join(["  " + str(p) for p in tried])
            raise FileNotFoundError(
                f"could not find {path} in any of the following locations:\n"
                f"{formatted_search_paths}"
            )

        # try to parse from json, so that return types are consistent
        # across FilesystemInputBundle and JSONInputBundle.
        if isinstance(res, FileInput):
            res = try_parse_abi(res)

        return res

    def add_search_path(self, path: PathLike) -> None:
        self.search_paths.append(path)

    # temporarily add something to the search path (within the
    # scope of the context manager) with highest precedence.
    # if `path` is None, do nothing
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

    # temporarily modify the top of the search path (within the
    # scope of the context manager) with highest precedence to something else
    @contextlib.contextmanager
    def poke_search_path(self, path: PathLike) -> Iterator[None]:
        tmp = self.search_paths[-1]
        self.search_paths[-1] = path
        try:
            yield
        finally:
            self.search_paths[-1] = tmp


# regular input. takes a search path(s), and `load_file()` will search all
# search paths for the file and read it from the filesystem
class FilesystemInputBundle(InputBundle):
    def _load_from_path(self, path: Path) -> CompilerInput:
        try:
            with path.open() as f:
                code = f.read()
        except (FileNotFoundError, NotADirectoryError):
            raise _NotFound(path)

        source_id = super()._generate_source_id(path)

        return FileInput(source_id, path, code)


# fake filesystem for JSON inputs. takes a base path, and `load_file()`
# "reads" the file from the JSON input. Note that this input bundle type
# never actually interacts with the filesystem -- it is guaranteed to be pure!
class JSONInputBundle(InputBundle):
    input_json: dict[PurePath, Any]

    def __init__(self, input_json, search_paths):
        super().__init__(search_paths)
        self.input_json = {}
        for path, item in input_json.items():
            path = _normpath(path)

            # should be checked by caller
            assert path not in self.input_json
            self.input_json[_normpath(path)] = item

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

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        # unreachable, based on how JSONInputBundle is constructed in
        # the codebase.
        raise JSONError(f"Unexpected type in file: '{path}'")  # pragma: nocover
