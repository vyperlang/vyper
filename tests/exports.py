import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from pytest import FixtureDef, Item


@dataclass
class TracedItem:
    name: str  # like test_concat or fixture_fixturename
    deps: list[str]
    traces: list[dict[str, Any]]


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir: Path = export_dir
        self.test_root: Path = test_root
        self.data: dict[Path, TracedItem] = {}
        self._current_item: Optional[TracedItem] = None
        self._executed_fixtures: list[str] = []
        self.output_file: Optional[Path] = None

    def append_fixture(self, fixture):
        # some fixtures don't have traces (e.g. `tx_failed`)
        # append only if it has traces
        if self._current_item.traces:
            self._executed_fixtures.append(fixture)

    def _resolve_dependencies(self, item: Union[FixtureDef, Item]):
        deps = item.fixturenames if isinstance(item, FixtureDef) else item.argnames
        deps_with_traces = []
        # traverse in the order in which the fixtures got executed
        for f in self._executed_fixtures:
            # some executed fixtures might be dependencies only of nodes higher
            # in the dependency graph, so we need a check
            if f in deps:
                # TODO we need a fully qualified name here
                deps_with_traces.append(f)

        self._current_item.deps = deps_with_traces

    def set_item(self, item: Union[FixtureDef, Item]):
        if isinstance(item, Item):
            module_file = Path(item.module.__file__).resolve()
        else:
            assert isinstance(item, FixtureDef)
            fixture_function = item.func
            f = fixture_function.__module__.__file__
            module_file = Path(f).resolve()

        rel_module = module_file.relative_to(self.test_root)

        item_name = item.name if isinstance(item, Item) else item.argname
        key = self.export_dir / rel_module / item_name

        if key not in self.data:
            self.data[key] = TracedItem(item.name, [], [])

        self._current_item = self.data[key]
        self._resolve_dependencies(item)

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
        self._current_item.traces.append(deployment)

    def trace_call(self, output: Optional[bytes], **call_args):
        if "calldata" in call_args:
            assert isinstance(call_args["calldata"], bytes)
            call_args["calldata"] = call_args["calldata"].hex()
        out_hex = output.hex() if output is not None else None

        call = {"trace_type": "call", "output": out_hex, "call_args": call_args}
        self._current_item.traces.append(call)

    def finalize_export(self):
        with open(self.output_file, "w") as f:
            json.dump(self.data, f, indent=2)
