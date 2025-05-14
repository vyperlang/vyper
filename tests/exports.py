import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir: Path = export_dir
        self.test_root: Path = test_root

        self.data: dict[str, dict[str, list[Any]]] = {}
        # some tests, e.g. `examples/` ones, deploy contracts in a separate fixture
        # which gets executed before the `pytest_runtest_call` hook, and thus
        # `set_item` wasn't yet called when tracing is performed.
        # we stash these "premature" traces and associate them
        # with a concrete test as soon as `set_item` is actually called
        self._stash: defaultdict[str, list[Any]] = defaultdict(list)

        self._current_test: Optional[dict[str, list[Any]]] = None
        self.output_file: Optional[Path] = None

    def set_item(self, item):
        module_file = Path(item.module.__file__).resolve()
        rel_module = module_file.relative_to(self.test_root)

        self.output_file = (self.export_dir / rel_module).with_suffix(rel_module.suffix + ".json")
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        test_name = item.name
        if test_name not in self.data:
            self.data[test_name] = {"deployments": [], "calls": []}
        self._current_test = self.data[test_name]
        self._merge_stash()

    def _get_target(self) -> dict[str, list[Any]]:
        return self._current_test or self._stash

    def _merge_stash(self):
        assert self._current_test is not None
        for key, items in self._stash.items():
            self._current_test.setdefault(key, []).extend(items)
        self._stash.clear()

    def trace_deployment(
        self,
        deployment_type: str,
        contract_abi: list[Any],
        deployed_address: str,
        initcode: str,
        runtime_bytecode: str,
        calldata: Optional[str],
        value: int,
        # Optional, deployment-type-specific fields:
        source_code: Optional[str] = None,
        annotated_ast: Optional[dict] = None,
        solc_json: Optional[dict] = None,
        raw_ir: Optional[str] = None,
        blueprint_initcode_prefix: Optional[str] = None,
    ):
        deployment = {
            "deployment_type": deployment_type,
            "contract_abi": contract_abi,
            "deployed_address": deployed_address,
            "initcode": initcode,
            "runtime_bytecode": runtime_bytecode,
            "calldata": calldata,
            "value": value,
            "source_code": source_code,
            "annotated_ast": annotated_ast,
            "solc_json": solc_json,
            "raw_ir": raw_ir,
            "blueprint_initcode_prefix": blueprint_initcode_prefix,
        }

        target = self._get_target()
        target.setdefault("deployments", []).append(deployment)

    def trace_call(self, output: bytes, **call_args):
        if "data" in call_args:
            assert isinstance(call_args["data"], bytes)
            call_args["data"] = call_args["data"].hex()

        target = self._get_target()
        target.setdefault("calls", []).append({"output": output.hex(), "call_args": call_args})

    def finalize_export(self):
        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)
