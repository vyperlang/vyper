from pathlib import Path
from typing import Sequence

from vyper import ast as vy_ast
from vyper.exceptions import StructureException
from vyper.typing import InterfaceImports, SourceCode


def get_interface_file_path(base_paths: Sequence, import_path: str) -> Path:
    relative_path = Path(import_path)
    for path in base_paths:
        # Find ABI JSON files
        file_path = path.joinpath(relative_path)
        suffix = next((i for i in (".vy", ".json") if file_path.with_suffix(i).exists()), None)
        if suffix:
            return file_path.with_suffix(suffix)

        # Find ethPM Manifest files (`from path.to.Manifest import InterfaceName`)
        # NOTE: Use file parent because this assumes that `file_path`
        #       coincides with an ABI interface file
        file_path = file_path.parent
        suffix = next((i for i in (".vy", ".json") if file_path.with_suffix(i).exists()), None)
        if suffix:
            return file_path.with_suffix(suffix)

    raise FileNotFoundError(f" Cannot locate interface '{import_path}{{.vy,.json}}'")


def extract_file_interface_imports(code: SourceCode) -> InterfaceImports:
    ast_tree = vy_ast.parse_to_ast(code)

    imports_dict: InterfaceImports = {}
    for node in ast_tree.get_children((vy_ast.Import, vy_ast.ImportFrom)):
        if isinstance(node, vy_ast.Import):  # type: ignore
            if not node.alias:
                raise StructureException("Import requires an accompanying `as` statement", node)
            if node.alias in imports_dict:
                raise StructureException(
                    f"Interface with alias {node.alias} already exists",
                    node,
                )
            imports_dict[node.alias] = node.name.replace(".", "/")
        elif isinstance(node, vy_ast.ImportFrom):  # type: ignore
            level = node.level  # type: ignore
            module = node.module or ""  # type: ignore
            if not level and module == "vyper.interfaces":
                # uses a builtin interface, so skip adding to imports
                continue

            base_path = ""
            if level > 1:
                base_path = "../" * (level - 1)
            elif level == 1:
                base_path = "./"
            base_path = f"{base_path}{module.replace('.','/')}/"

            if node.name in imports_dict and imports_dict[node.name] != f"{base_path}{node.name}":
                raise StructureException(
                    f"Interface with name {node.name} already exists",
                    node,
                )
            imports_dict[node.name] = f"{base_path}{node.name}"

    return imports_dict
