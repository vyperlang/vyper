from typing import Any

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
    base_path: str

    contract_sources: dict[Path, str]

    def _resolve_path(self, filename) -> Path:
        filepath = Path(filename)
        return filepath.resolve().relative_to(self.base_path)

    def load_file(self, filename: str) -> str:
        filepath = self._resolve_path(filename)
        return self._load_file(filename)

    def _load_file(self, ) -> CompilerInput:
        raise NotImplementedError(f"not implemented! {self.__class__}.load_file()")


# regular input. takes a base path, and `load_file()` does what you think,
# it reads a file from the filesystem
@dataclass
class FilesystemInputBundle(InputBundle):
    def _load_file(self, path: Path) -> CompilerInput:
        with path.open() as f:
            code = f.read()

# fake filesystem for JSON inputs. takes a base path, and `load_file()`
# "reads" the file from the JSON input
@dataclass
class JSONInputBundle(InputBundle):
    input_json: Any

    # pseudocode
    def _load_file(self, path: Path) -> CompilerInput:
        contents = self.input_json[path]
        if "abi" in contents:
            return ABIInput(contents["abi"])

        if isinstance(contents, list):
            return ABIInput(contents)

        # TODO: ethPM support
        #if isinstance(contents, dict) and "contractTypes" in contents:

        # TODO: raise JSONError instead of ValueError?
        raise ValueError(f"Unexpected type in file: '{path}'")
