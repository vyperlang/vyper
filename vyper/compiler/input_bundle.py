import contextlib
import json
import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path, PurePath
from typing import Any, Iterator, Optional

from vyper.exceptions import JSONError
from vyper.utils import sha256sum

# a type to make mypy happy
PathLike = Path | PurePath


@dataclass
class CompilerInput:
    # an input to the compiler, basically an abstraction for file contents
    source_id: int
    path: PathLike  # the path that was asked for

    # resolved_path is the real path that was resolved to.
    # mainly handy for debugging at this point
    resolved_path: PathLike


@dataclass
class FileInput(CompilerInput):
    source_code: str

    @cached_property
    def sha256sum(self):
        return sha256sum(self.source_code)


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
        return ABIInput(file_input.source_id, file_input.path, file_input.resolved_path, s)
    except (ValueError, TypeError):
        return file_input


class _NotFound(Exception):
    pass


# an opaque object which consumers can get/set attributes on
class _Cache(object):
    pass


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

        # this is a little bit cursed, but it allows consumers to cache data
        # that share the same lifetime as this input bundle.
        self._cache = _Cache()

    def _normalize_path(self, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._normalize_path()")

    def _load_from_path(self, resolved_path, path):
        raise NotImplementedError(f"not implemented! {self.__class__}._load_from_path()")

    def _generate_source_id(self, resolved_path: PathLike) -> int:
        # Note: it is possible for a file to get in here more than once,
        # e.g. by symlink
        if resolved_path not in self._source_ids:
            self._source_ids[resolved_path] = self._source_id_counter
            self._source_id_counter += 1

        return self._source_ids[resolved_path]

    def load_file(self, path: PathLike | str) -> CompilerInput:
        # search path precedence
        tried = []
        for sp in reversed(self.search_paths):
            # note from pathlib docs:
            # > If the argument is an absolute path, the previous path is ignored.
            # Path("/a") / Path("/b") => Path("/b")
            to_try = sp / path

            try:
                to_try = self._normalize_path(to_try)
                res = self._load_from_path(to_try, path)
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
    def _normalize_path(self, path: Path) -> Path:
        # normalize the path with os.path.normpath, to break down
        # things like "foo/bar/../x.vy" => "foo/x.vy", with all
        # the caveats around symlinks that os.path.normpath comes with.
        try:
            return path.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            raise _NotFound(path)

    def _load_from_path(self, resolved_path: Path, original_path: Path) -> CompilerInput:
        try:
            with resolved_path.open() as f:
                code = f.read()
        except (FileNotFoundError, NotADirectoryError):
            raise _NotFound(resolved_path)

        source_id = super()._generate_source_id(resolved_path)

        return FileInput(source_id, original_path, resolved_path, code)


# wrap os.path.normpath, but return the same type as the input
def _normpath(path):
    return path.__class__(os.path.normpath(path))


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
            self.input_json[path] = item

    def _normalize_path(self, path: PurePath) -> PurePath:
        return _normpath(path)

    def _load_from_path(self, resolved_path: PurePath, original_path: PurePath) -> CompilerInput:
        try:
            value = self.input_json[resolved_path]
        except KeyError:
            raise _NotFound(resolved_path)

        source_id = super()._generate_source_id(resolved_path)

        if "content" in value:
            return FileInput(source_id, original_path, resolved_path, value["content"])

        if "abi" in value:
            return ABIInput(source_id, original_path, resolved_path, value["abi"])

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        # unreachable, based on how JSONInputBundle is constructed in
        # the codebase.
        raise JSONError(f"Unexpected type in file: '{resolved_path}'")  # pragma: nocover
