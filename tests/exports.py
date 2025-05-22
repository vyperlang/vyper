import json
import sys
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
        # module_path -> all traced items in the module
        self.data: dict[Path, list[TracedItem]] = {}
        self._current_module: Optional[Path] = None
        self._executed_fixtures: list[Path] = []

    def _resolve_dependencies(self, node: Union[FixtureDef, Item]):
        deps = node.argnames if isinstance(node, FixtureDef) else node.fixturenames
        deps_with_traces = []
        # traverse in the order in which the fixtures got executed
        for f in self._executed_fixtures:
            # some executed fixtures might be dependencies only of nodes higher
            # in the dependency graph, so we need a check
            if f.name in deps:
                deps_with_traces.append(str(f))

        self.current_item.deps = deps_with_traces

    @property
    def current_item(self) -> TracedItem:
        assert self._current_module is not None, "set_item() not called yet"
        print(f"_current_module: {self._current_module}")
        bucket = self.data[self._current_module]
        assert bucket, "internal error: empty bucket"
        return bucket[-1]

    def set_item(self, node: Union[FixtureDef, Item]):
        if isinstance(node, Item):
            module_path = Path(node.module.__file__).resolve()
        else:
            # TODO hacky, can we retrieve the path more conveniently?
            func = node.func
            module_obj = sys.modules[func.__module__]
            module_path = Path(module_obj.__file__).resolve()

        rel_module = module_path.relative_to(self.test_root)

        path = self.export_dir / rel_module

        item_name = node.name if isinstance(node, Item) else node.argname
        if path not in self.data:
            # TODO we probably need to number the item names if they're fixtures
            self.data[path] = [TracedItem(item_name, [], [])]
        else:
            self.data[path].append(TracedItem(item_name, [], []))

        self._current_module = path
        self._resolve_dependencies(node)
        if isinstance(node, Item):
            # TODO maybe rename to finalize fixture?
            # a test item is the last item in the dependency graph, we should clear
            self._executed_fixtures.clear()

    def finalize_item(self, node: Union[FixtureDef, Item]):
        # normal test items currently don't need any finalization
        assert isinstance(node, FixtureDef)
        fixture_path = self._current_module / node.argname
        if self.current_item.traces:
            if fixture_path not in self._executed_fixtures:
                self._executed_fixtures.append(fixture_path)

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
        self.current_item.traces.append(deployment)

    def trace_call(self, output: Optional[bytes], **call_args):
        if "calldata" in call_args:
            assert isinstance(call_args["calldata"], bytes)
            call_args["calldata"] = call_args["calldata"].hex()
        out_hex = output.hex() if output is not None else None

        call = {"trace_type": "call", "output": out_hex, "call_args": call_args}
        self.current_item.traces.append(call)

    def finalize_export(self):
        for module_path, traced_items in self.data.items():
            json_path = module_path.with_suffix(".json")
            json_path.parent.mkdir(parents=True, exist_ok=True)

            with json_path.open("w", encoding="utf-8") as fp:
                json.dump([ti.__dict__ for ti in traced_items], fp, indent=2, sort_keys=True)
