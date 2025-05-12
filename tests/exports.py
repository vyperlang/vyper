import json
from pathlib import Path
from typing import Any, Optional


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir: Path = export_dir
        self.test_root: Path = test_root

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
            self.data[test_name] = {"deployments": [], "calls": []}
        self._current_item = self.data[test_name]

    def trace_deployment(
        self,
        source_code: str,
        contract_abi: list[Any],
        deployed_address: str,
        initcode: str,
        runtime_bytecode: str,
        calldata: str,
        value: int,
    ):
        self._current_item["deployments"].append(
            {
                "source_code": source_code,
                "contract_abi": contract_abi,
                "deployed_address": deployed_address,
                "initcode": initcode,
                "runtime_bytecode": runtime_bytecode,
                "calldata": calldata,
                "value": value,
            }
        )

    def trace_call(self, output: bytes, **call_args):
        calls_list = self._current_item["calls"]

        if "data" in call_args:
            assert isinstance(call_args["data"], bytes)
            call_args["data"] = call_args["data"].hex()

        calls_list.append({
            "output": output.hex(),
            "call_args": call_args,
        })


    def finalize_export(self):
        # nothing to write if no tests ran in this module
        if not self.data or self.output_file is None:
            return

        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)