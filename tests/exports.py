import json
from pathlib import Path
from typing import Any, Optional


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir: Path = export_dir
        self.test_root: Path = test_root

        # {"test_name": { "deployments": [...], # later add "calls": [...] }}
        self.data: dict[str, dict[str, list[Any]]] = {}

        self._current_item: Optional[dict[str, list[Any]]] = None
        self.output_file: Optional[Path] = None

    def set_item(self, item: "pytest.Item"):
        module_file = Path(item.module.__file__).resolve()
        rel_module = module_file.relative_to(self.test_root)

        self.output_file = (self.export_dir / rel_module).with_suffix(
            rel_module.suffix + ".json"
        )
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        test_name = item.name
        if test_name not in self.data:
            self.data[test_name] = {"deployments": []}
        self._current_item = self.data[test_name]

    def trace_deployment(
        self,
        source_code: str,
        contract_abi: list[Any],
        deployed_address: str,
        initcode: str,
        runtime_bytecode: str,
        calldata: str,
        python_ctor_args: dict[str, Any],
        value: int,
    ):
        assert self._current_item is not None

        def serialize_python_arg(val: Any) -> Any:
            if isinstance(val, bytes):
                return val.hex()
            try:
                json.dumps(val)
                return val
            except TypeError:
                return str(val)

        serialized_args = [
            serialize_python_arg(a) for a in python_ctor_args.get("args", [])
        ]
        serialized_kwargs = {
            k: serialize_python_arg(v)
            for k, v in python_ctor_args.get("kwargs", {}).items()
        }

        self._current_item["deployments"].append(
            {
                "source_code": source_code,
                "contract_abi": contract_abi,
                "deployed_address": deployed_address,
                "initcode": initcode,
                "runtime_bytecode": runtime_bytecode,
                "calldata": calldata,
                "python_ctor_args": {"args": serialized_args, "kwargs": serialized_kwargs},
                "value": value,
            }
        )

    def finalize_export(self):
        # nothing to write if no tests ran in this module
        if not self.data or self.output_file is None:
            return

        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)