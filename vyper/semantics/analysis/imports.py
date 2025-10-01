import contextlib
import dataclasses as dc
import json
from dataclasses import asdict, dataclass
from pathlib import Path, PurePath
from typing import Any, Iterator, Optional

import vyper.builtins.interfaces
import vyper.builtins.stdlib
from vyper import ast as vy_ast
from vyper.compiler.input_bundle import (
    BUILTIN,
    CompilerInput,
    FileInput,
    FilesystemInputBundle,
    InputBundle,
    JSONInput,
    PathLike,
)
from vyper.exceptions import (
    DuplicateImport,
    ImportCycle,
    ModuleNotFound,
    StructureException,
    tag_exceptions,
)
from vyper.semantics.analysis.base import ImportInfo
from vyper.utils import OrderedSet, safe_relpath, sha256sum

"""
collect import statements and validate the import graph.
this module is separated into its own pass so that we can resolve the import
graph quickly (without doing semantic analysis) and for cleanliness, to
segregate the I/O portion of semantic analysis into its own pass.
"""


@dataclass
class _ImportGraph:
    # the current path in the import graph traversal
    _path: list[vy_ast.Module] = dc.field(default_factory=list)

    # stack of dicts, each item in the stack is a dict keeping
    # track of imports in the current module
    _imports: list[dict] = dc.field(default_factory=list)

    @property
    def imported_modules(self):
        return self._imports[-1]

    @property
    def current_module(self):
        return self._path[-1]

    def push_path(self, module_ast: vy_ast.Module) -> None:
        if module_ast in self._path:
            cycle = self._path + [module_ast]
            raise ImportCycle(" imports ".join(f'"{t.path}"' for t in cycle))

        self._path.append(module_ast)
        self._imports.append({})

    def pop_path(self, expected: vy_ast.Module) -> None:
        popped = self._path.pop()
        assert expected is popped, "unreachable"
        self._imports.pop()

    @contextlib.contextmanager
    def enter_path(self, module_ast: vy_ast.Module) -> Iterator[None]:
        self.push_path(module_ast)
        try:
            yield
        finally:
            self.pop_path(module_ast)


def try_parse_abi(file_input: FileInput) -> CompilerInput:
    try:
        s = json.loads(file_input.source_code)
        if isinstance(s, dict) and "abi" in s:
            s = s["abi"]
        return JSONInput(**asdict(file_input), data=s)
    except (ValueError, TypeError):
        return file_input


class ImportAnalyzer:
    seen: OrderedSet[vy_ast.Module]
    _compiler_inputs: dict[CompilerInput, vy_ast.Module]
    toplevel_module: vy_ast.Module

    def __init__(self, input_bundle: InputBundle, graph: _ImportGraph, module_ast: vy_ast.Module):
        self.input_bundle = input_bundle
        self.graph = graph
        self.toplevel_module = module_ast
        self._ast_of: dict[int, vy_ast.Module] = {}

        self.seen = OrderedSet()

        # keep around compiler inputs so when we construct the output
        # bundle, we have access to the compiler input for each module
        self._compiler_inputs = {}

        self._integrity_sum = None

        # should be all system paths + topmost module path
        self.absolute_search_paths = input_bundle.search_paths.copy()

    def resolve_imports(self):
        self._resolve_imports_r(self.toplevel_module)
        self._integrity_sum = self._calculate_integrity_sum_r(self.toplevel_module)

    @property
    def compiler_inputs(self) -> dict[CompilerInput, vy_ast.Module]:
        return self._compiler_inputs

    def _calculate_integrity_sum_r(self, module_ast: vy_ast.Module):
        acc = [sha256sum(module_ast.full_source_code)]
        for s in module_ast.get_children((vy_ast.Import, vy_ast.ImportFrom)):
            info = s._metadata["import_info"]

            if info.compiler_input.path.suffix in (".vyi", ".json"):
                # NOTE: this needs to be redone if interfaces can import other interfaces
                acc.append(info.compiler_input.sha256sum)
            else:
                acc.append(self._calculate_integrity_sum_r(info.parsed))

        return sha256sum("".join(acc))

    def _resolve_imports_r(self, module_ast: vy_ast.Module):
        if module_ast in self.seen:
            return
        with self.graph.enter_path(module_ast):
            for node in module_ast.body:
                with tag_exceptions(node):
                    if isinstance(node, vy_ast.Import):
                        self._handle_Import(node)
                    elif isinstance(node, vy_ast.ImportFrom):
                        self._handle_ImportFrom(node)

        self.seen.add(module_ast)

    def _handle_Import(self, node: vy_ast.Import):
        # import x.y[name] as y[alias]

        alias = node.alias

        if alias is None:
            alias = node.name

        # don't handle things like `import x.y`
        if "." in alias:
            msg = "import requires an accompanying `as` statement"
            suggested_alias = node.name[node.name.rfind(".") :]
            hint = f"try `import {node.name} as {suggested_alias}`"
            raise StructureException(msg, node, hint=hint)

        self._add_import(node, 0, node.name, alias)

    def _handle_ImportFrom(self, node: vy_ast.ImportFrom):
        # from m.n[module] import x[name] as y[alias]

        alias = node.alias

        if alias is None:
            alias = node.name

        module = node.module or ""
        if module:
            module += "."

        qualified_module_name = module + node.name
        self._add_import(node, node.level, qualified_module_name, alias)

    def _add_import(
        self, node: vy_ast.VyperNode, level: int, qualified_module_name: str, alias: str
    ) -> None:
        compiler_input, ast = self._load_import(node, level, qualified_module_name, alias)
        self._compiler_inputs[compiler_input] = ast
        node._metadata["import_info"] = ImportInfo(
            alias, qualified_module_name, compiler_input, ast
        )

    # load an InterfaceT or ModuleInfo from an import.
    # raises FileNotFoundError
    def _load_import(
        self, node: vy_ast.VyperNode, level: int, module_str: str, alias: str
    ) -> tuple[CompilerInput, Any]:
        if _is_builtin(level, module_str):
            return _load_builtin_import(level, module_str)

        path = _import_to_path(level, module_str)

        if path in self.graph.imported_modules:
            previous_import_stmt = self.graph.imported_modules[path]
            raise DuplicateImport(f"{alias} imported more than once!", previous_import_stmt, node)

        self.graph.imported_modules[path] = node

        err = None

        try:
            path_vy = path.with_suffix(".vy")
            file = self._load_file(path_vy, level)
            assert isinstance(file, FileInput)  # mypy hint

            module_ast = self._ast_from_file(file)
            self._resolve_imports_r(module_ast)

            return file, module_ast

        except FileNotFoundError as e:
            # escape `e` from the block scope, it can make things
            # easier to debug.
            err = e

        try:
            file = self._load_file(path.with_suffix(".vyi"), level)
            assert isinstance(file, FileInput)  # mypy hint
            module_ast = self._ast_from_file(file)
            self._resolve_imports_r(module_ast)

            return file, module_ast

        except FileNotFoundError:
            pass

        try:
            file = self._load_file(path.with_suffix(".json"), level)
            if isinstance(file, FileInput):
                file = try_parse_abi(file)
            assert isinstance(file, JSONInput)  # mypy hint
            return file, file.data
        except FileNotFoundError:
            pass

        hint = None
        if module_str.startswith("vyper.interfaces"):
            hint = "try renaming `vyper.interfaces` to `ethereum.ercs`"

        # copy search_paths, makes debugging a bit easier
        search_paths = self.input_bundle.search_paths.copy()  # noqa: F841
        raise ModuleNotFound(module_str, hint=hint) from err

    def _load_file(self, path: PathLike, level: int) -> CompilerInput:
        ast = self.graph.current_module

        search_paths: list[PathLike]  # help mypy
        if level != 0:  # relative import
            search_paths = [Path(ast.resolved_path).parent]
        else:
            search_paths = self.absolute_search_paths

        with self.input_bundle.temporary_search_paths(search_paths):
            return self.input_bundle.load_file(path)

    def _ast_from_file(self, file: FileInput) -> vy_ast.Module:
        # cache ast if we have seen it before.
        # this gives us the additional property of object equality on
        # two ASTs produced from the same source
        ast_of = self._ast_of
        if file.source_id not in ast_of:
            ast_of[file.source_id] = _parse_ast(file)

        return ast_of[file.source_id]


def _parse_ast(file: FileInput) -> vy_ast.Module:
    module_path = file.resolved_path  # for error messages
    try:
        # try to get a relative path, to simplify the error message
        cwd = Path(".")
        if module_path.is_absolute():
            cwd = cwd.resolve()
        module_path = module_path.relative_to(cwd)
    except ValueError:
        # we couldn't get a relative path (cf. docs for Path.relative_to),
        # use the resolved path given to us by the InputBundle
        pass

    is_interface = file.resolved_path.suffix == ".vyi"
    ret = vy_ast.parse_to_ast(
        file.source_code,
        source_id=file.source_id,
        module_path=module_path.as_posix(),
        resolved_path=file.resolved_path.as_posix(),
        is_interface=is_interface,
    )
    return ret


# convert an import to a path (without suffix)
def _import_to_path(level: int, module_str: str) -> PurePath:
    base_path = ""
    if level > 1:
        base_path = "../" * (level - 1)
    elif level == 1:
        base_path = "./"
    return PurePath(f"{base_path}{module_str.replace('.', '/')}/")


_builtins_cache: dict[PathLike, tuple[CompilerInput, vy_ast.Module]] = {}

# builtin import path -> (prefix for removal, package, suffix)
BUILTIN_MODULE_RULES = {
    "ethereum.ercs": ("ethereum.ercs", vyper.builtins.interfaces.__package__, ".vyi"),
    "math": ("", vyper.builtins.stdlib.__package__, ".vy"),
}


# TODO: could move this to analysis/common.py or something
def _get_builtin_prefix(module_str: str) -> Optional[str]:
    for prefix in BUILTIN_MODULE_RULES.keys():
        if module_str.startswith(prefix):
            return prefix
    return None


def _is_builtin(level: int, module_str: str) -> bool:
    return level == 0 and _get_builtin_prefix(module_str) is not None


def _load_builtin_import(level: int, module_str: str) -> tuple[CompilerInput, vy_ast.Module]:
    module_prefix = _get_builtin_prefix(module_str)
    assert module_prefix is not None, "unreachable"

    assert level == 0, "builtin imports are absolute"

    builtins_path = vyper.builtins.__path__[0]
    # hygiene: convert to relpath to avoid leaking user directory info
    # (note Path.relative_to cannot handle absolute to relative path
    # conversion, so we must use the `os` module).
    builtins_path = safe_relpath(builtins_path)

    search_path = Path(builtins_path).parent.parent
    # generate an input bundle just because it knows how to build paths.
    input_bundle = FilesystemInputBundle([search_path])

    remove_prefix, target_package, suffix = BUILTIN_MODULE_RULES[module_prefix]
    base_name = module_str.removeprefix(remove_prefix + ".")
    remapped_module = f"{target_package}.{base_name}"

    path = _import_to_path(level, remapped_module)
    path = path.with_suffix(suffix)

    # builtins are globally the same, so we can safely cache them
    # (it is also *correct* to cache them, so that types defined in builtins
    # compare correctly using pointer-equality.)
    if path in _builtins_cache:
        file, ast = _builtins_cache[path]
        return file, ast

    try:
        file = input_bundle.load_file(path)
        # set source_id to builtin sentinel value
        file = dc.replace(file, source_id=BUILTIN)
        assert isinstance(file, FileInput)  # mypy hint
    except FileNotFoundError as e:
        hint = None
        components = module_str.split(".")
        # common issue for upgrading codebases from v0.3.x to v0.4.x -
        # hint: rename ERC20 to IERC20
        if components[-1].startswith("ERC"):
            module_prefix = components[-1]
            hint = f"try renaming `{module_prefix}` to `I{module_prefix}`"
        raise ModuleNotFound(module_str, hint=hint) from e

    builtin_ast = _parse_ast(file)

    # no recursion needed since builtins don't have any imports

    _builtins_cache[path] = file, builtin_ast
    return file, builtin_ast


def resolve_imports(module_ast: vy_ast.Module, input_bundle: InputBundle):
    graph = _ImportGraph()
    analyzer = ImportAnalyzer(input_bundle, graph, module_ast)
    analyzer.resolve_imports()

    return analyzer
