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
class ABIFile(CompilerInput):
    # some json file, either regular ABI or ethPM manifest v3 (EIP-2687)
    abi: Any


@dataclass
class InputBundle:
    base_path: str

    def _resolve_path(self, filename) -> Path:
        filepath = Path(filename)
        return filepath.resolve().relative_to(self.base_path)

    def load_file(self, filename: str) -> str:
        filepath = self._resolve_path(filename)
        return self._load_file(filename)

    def _load_file(self, ) -> CompilerInput:
        raise NotImplementedError(f"not implemented! {self.__class__}.load_file()")


@dataclass
class FilesystemInput(InputBundle):
    def _load_file(self, path: Path) -> str:
        with path.open() as f:
            return f.read()

@dataclass
class JSONInput(InputBundle):
    input_json: dict

    # pseudocode
    def _load_file(self, path: Path) -> str:
        return self.input_json[path]
