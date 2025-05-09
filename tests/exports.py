import json
from pathlib import Path
from typing import Any, Optional


class TestExporter:
    def __init__(self, output_file_path: Path, test_root: Path):
        self.output_file: Path = output_file_path
        # {"module_name": ["test_name_1", "test_name_2", ...]}
        # {
        #   "relative/path/to/module.py": {
        #     "test_name_1": {
        #       "deployments": [
        #         {"source_code": "...", "address": "...", ...}
        #       ],
        #       # "calls": [] # add this key later
        #     },
        #     ...
        #   },
        #   ...
        # }
        self.data: dict[str, dict[str, dict[str, list[Any]]]] = {}

        self.test_root: Path = test_root
        self._current_item: Optional[Any] = None

    def set_item(self, item: 'pytest.Item'):
        module_file_path = Path(item.module.__file__).resolve()
        relative_module_path = module_file_path.relative_to(self.test_root)
        module_path = str(relative_module_path)
        test_name = item.name  # eg "test_abi_decode"

        if module_path not in self.data:
            self.data[module_path] = {}

        if test_name not in self.data[module_path]:
            self.data[module_path][test_name] = {
                "deployments": [],
                # "calls": [] # Add when implementing call tracing
            }

        self._current_item = self.data[module_path][test_name]

    def trace_deployment(
            self,
            source_code: str,
            contract_abi: list,
            deployed_address: str,
            initcode: str,
            runtime_bytecode: str,
            calldata: str,
            python_ctor_args: dict,
            value: int,
    ):
        assert self._current_item is not None

        def serialize_python_arg(val):
            if isinstance(val, bytes):
                return val.hex()
            try:
                json.dumps(val)
                return val
            except TypeError:
                return str(val)

        serialized_py_args = [serialize_python_arg(arg) for arg in python_ctor_args.get("args", [])]
        serialized_py_kwargs = {k: serialize_python_arg(v) for k, v in
                                python_ctor_args.get("kwargs", {}).items()}

        current = self._current_item["deployments"]
        current.append({
            "source_code": source_code,
            "contract_abi": contract_abi,
            "deployed_address": deployed_address,
            "initcode": initcode,
            "runtime_bytecode": runtime_bytecode,
            "calldata": calldata,
            "python_ctor_args": {
                "args": serialized_py_args,
                "kwargs": serialized_py_kwargs
            },
            "value": value,
        })

    def finalize_export(self):
        if not self.data:
            print("No test data recorded.")
            return

        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)