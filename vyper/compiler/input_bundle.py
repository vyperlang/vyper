from dataclasses import dataclass
from typing import Any

from pathlib import Path, PurePath


# stub
class CompilerInput:
    # an input to the compiler.
    pass


# stub
@dataclass
class VyFile(CompilerInput):
    source_code: str


# stub
@dataclass
class ABIInput(CompilerInput):
    # some json file, either regular ABI or ethPM manifest v3 (EIP-2687)
    abi: Any


@dataclass
class InputBundle:
    search_paths: list[Path]
    compilation_targets: list[Path]

    def load_file(self, relative_path: str) -> str:
        raise NotImplementedError(f"not implemented! {self.__class__}.load_file()")


# regular input. takes a search path(s), and `load_file()` will search all
# search paths for the file and read it from the filesystem
@dataclass
class FilesystemInputBundle(InputBundle):
    def load_file(self, path: Path) -> CompilerInput:
        assert len(search_paths) > 0  # at least, should contain pwd

        for p in search_paths:
            try:
                # note from pathlib docs:
                # > If the argument is an absolute path, the previous path is ignored.
                # Path("/a") / Path("/b") => Path("/b")
                to_try = p / path
                with to_try.open() as f:
                    code = f.read()
                    return VyInput(code)
            except FileNotFoundError:
                continue
        else:
            formatted_search_paths = "\n".join(["  " + str(sp) for sp in search_paths])
            raise FileNotFoundError(
                f"could not find {path} within any of the following search "
                f"paths: {formatted_search_paths}"
            )

        raise CompilerPanic("unreachable")  # pragma: nocover


# fake filesystem for JSON inputs. takes a base path, and `load_file()`
# "reads" the file from the JSON input
@dataclass
class JSONInputBundle(InputBundle):
    input_json: dict[PurePath, Any]

    # pseudocode
    def _load_file(self, path: PurePath) -> CompilerInput:
        path = PurePath(path)
        try:
            contents = self.input_json[path]
        except KeyError:
            # TODO double check that this is what is expected
            raise FileNotFoundError(path)

        if "abi" in contents:
            return ABIInput(contents["abi"])

        if isinstance(contents, list):
            return ABIInput(contents)

        # TODO: ethPM support
        # if isinstance(contents, dict) and "contractTypes" in contents:

        # TODO: raise JSONError instead of ValueError?
        raise ValueError(f"Unexpected type in file: '{path}'")
