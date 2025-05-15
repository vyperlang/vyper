import json
from pathlib import Path
from typing import Any, Optional


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir: Path = export_dir
        self.test_root: Path = test_root

        self.data: dict[str, list[dict[str, Any]]] = {}
        # some tests, e.g. `examples/` ones, deploy contracts in a separate fixture
        # which gets executed before the `pytest_runtest_call` hook, and thus
        # `set_item` wasn't yet called when tracing is performed.
        # we stash these "premature" traces and associate them
        # with a concrete test as soon as `set_item` is actually called
        self._stash: list[dict[str, Any]] = []

        self._current_test: Optional[list[dict[str, Any]]] = None
        self.output_file: Optional[Path] = None

    def set_item(self, item):
        module_file = Path(item.module.__file__).resolve()
        rel_module = module_file.relative_to(self.test_root)

        self.output_file = (self.export_dir / rel_module).with_suffix(rel_module.suffix + ".json")
        self.output_file.parent.mkdir(parents=True, exist_ok=True)

        test_name = item.name
        if test_name not in self.data:
            self.data[test_name] = []
        self._current_test = self.data[test_name]
        self._merge_stash()

    def _get_target(self) -> list[dict[str, Any]]:
        return self._current_test if self._current_test is not None else self._stash

    def _merge_stash(self):
        # move any earlier traces into the real test list, preserving order
        assert self._current_test is not None
        if self._stash:
            self._current_test.extend(self._stash)
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
        deployment_succeeded: bool = True,
        source_code: Optional[str] = None,
        annotated_ast: Optional[dict] = None,
        solc_json: Optional[dict] = None,
        raw_ir: Optional[str] = None,
        blueprint_initcode_prefix: Optional[str] = None,
    ):
        deployment = {
            "trace_type": "deployment",
            "deployment_type": deployment_type,
            "contract_abi": contract_abi,
            "deployed_address": deployed_address,
            "initcode": initcode,
            "runtime_bytecode": runtime_bytecode,
            "calldata": calldata,
            "value": value,
            "deployment_succeeded": deployment_succeeded,
            "source_code": source_code,
            "annotated_ast": annotated_ast,
            "solc_json": solc_json,
            "raw_ir": raw_ir,
            "blueprint_initcode_prefix": blueprint_initcode_prefix,
        }
        self._get_target().append(deployment)

    def trace_call(self, output: Optional[bytes], **call_args):
        if "calldata" in call_args:
            assert isinstance(call_args["calldata"], bytes)
            call_args["calldata"] = call_args["calldata"].hex()
        out_hex = output.hex() if output is not None else None

        call = {"trace_type": "call", "output": out_hex, "call_args": call_args}
        self._get_target().append(call)

    def finalize_export(self):
        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)
