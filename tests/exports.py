import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from pytest import FixtureDef, Item

SEP = "__"

# Export path for a module: tests/functional/foo/test_bar.py -> <export_dir>/functional/foo/test_bar
# All items (tests/fixtures) defined in the same module share an export path (and output JSON).


def _module_export_path(
    node: Union[FixtureDef, Item], test_root: Path, export_root: Path
) -> Optional[Path]:
    if isinstance(node, Item):
        mod_file = Path(node.module.__file__).resolve()
    else:  # FixtureDef
        mod_file = Path(sys.modules[node.func.__module__].__file__).resolve()

    # built-in fixtures can live outside test root
    try:
        rel = mod_file.relative_to(test_root)
    except ValueError:
        return None  # external fixture

    return export_root / rel


@dataclass
class TracedItem:
    name: str
    deps: list[str]
    traces: list[dict[str, Any]]
    item_type: str


@dataclass
class PendingFixture:
    """
    Temporary state held while a fixture is executing.
    Stores scope and requesting context needed to later register in the timeline.
    """

    traced_item: TracedItem
    definition_module_path: Path
    unique_name: str
    scope: str
    requesting_module_path: Optional[Path]
    requesting_test_nodeid: Optional[str]


@dataclass(frozen=True)
class ActiveFixture:
    """
    An executed fixture in the chronological timeline.
    Used by _deps_for() to compute dependencies filtered by scope/requester.
    """

    ref: str
    scope: str
    requesting_module_path: Optional[Path]
    requesting_test_nodeid: Optional[str]


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir = export_dir
        self.test_root = test_root

        self.data: dict[Path, list[TracedItem]] = {}
        self._counts: dict[tuple[Path, str], int] = {}
        self._active_fixtures: list[ActiveFixture] = []
        self._pending: dict[int, PendingFixture] = {}
        self._item_stack: list[TracedItem] = []

    @property
    def current_item(self) -> TracedItem:
        assert self._item_stack, "set_item() not called yet"
        return self._item_stack[-1]

    def _get_requesting_module_path(self, request) -> Optional[Path]:
        try:
            mod_file = Path(request.node.module.__file__).resolve()
        except AttributeError:
            nodeid = request.node.nodeid
            mod_path_str = nodeid.split("::", 1)[0]
            project_root = self.test_root.parent
            mod_file = (project_root / mod_path_str).resolve()

        try:
            rel = mod_file.relative_to(self.test_root)
        except ValueError:
            return None

        return self.export_dir / rel

    # Dependencies should reflect the chronological execution timeline
    # of fixtures that affect chain state, filtered by fixture scope,
    # not by what the test explicitly requests.
    # NOTE: O(items × active_fixtures) - pruning old fixtures by scope would help.
    def _deps_for(
        self, requesting_module_path: Optional[Path], requesting_test_nodeid: Optional[str]
    ) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        for af in self._active_fixtures:
            if af.scope == "session":
                ref = af.ref
            elif af.scope == "module":
                if (
                    requesting_module_path is None
                    or af.requesting_module_path != requesting_module_path
                ):
                    continue
                ref = af.ref
            elif af.scope == "function":
                if (
                    requesting_test_nodeid is None
                    or af.requesting_test_nodeid != requesting_test_nodeid
                ):
                    continue
                ref = af.ref
            else:
                continue

            if ref not in seen:
                seen.add(ref)
                out.append(ref)

        return out

    def set_item(self, node: Union[FixtureDef, Item], *, request=None) -> bool:
        module_path = _module_export_path(node, self.test_root, self.export_dir)

        if module_path is None:
            return False

        lst = self.data.setdefault(module_path, [])

        if isinstance(node, Item):
            traced_item = TracedItem(node.name, [], [], "test")
            lst.append(traced_item)
            self._item_stack.append(traced_item)
            test_nodeid = node.nodeid
            traced_item.deps = self._deps_for(module_path, test_nodeid)
            return True

        assert isinstance(node, FixtureDef)

        base = node.argname
        key = (module_path, base)
        scope = str(node.scope) if hasattr(node, "scope") else "function"

        assert scope in (
            "session",
            "module",
            "function",
        ), f"unsupported fixture scope {scope!r} for {base!r}"

        requesting_module_path: Optional[Path] = None
        requesting_test_nodeid: Optional[str] = None

        if request is not None:
            if scope == "session":
                pass
            elif scope == "module":
                requesting_module_path = self._get_requesting_module_path(request)
            else:
                requesting_module_path = self._get_requesting_module_path(request)
                requesting_test_nodeid = request.node.nodeid

        count = self._counts.get(key, 0) + 1
        self._counts[key] = count
        unique = base if count == 1 else f"{base}{SEP}{count}"
        traced_item = TracedItem(unique, [], [], "fixture")
        lst.append(traced_item)
        self._item_stack.append(traced_item)
        traced_item.deps = self._deps_for(requesting_module_path, requesting_test_nodeid)

        self._pending[id(node)] = PendingFixture(
            traced_item=traced_item,
            definition_module_path=module_path,
            unique_name=unique,
            scope=scope,
            requesting_module_path=requesting_module_path,
            requesting_test_nodeid=requesting_test_nodeid,
        )

        return True

    def finalize_test(self):
        assert self._item_stack, "finalize_test() called without a current test item"
        self._item_stack.pop()

    def finalize_item(self, node: Union[FixtureDef, Item]):
        if isinstance(node, Item):
            return

        pending = self._pending.pop(id(node))
        self._item_stack.pop()

        if not pending.traced_item.traces:
            self.data[pending.definition_module_path].remove(pending.traced_item)
            return

        json_path = pending.definition_module_path.with_suffix(".json")
        ref = (json_path / pending.unique_name).as_posix()

        self._active_fixtures.append(
            ActiveFixture(
                ref=ref,
                scope=pending.scope,
                requesting_module_path=pending.requesting_module_path,
                requesting_test_nodeid=pending.requesting_test_nodeid,
            )
        )

    def trace_deployment(self, **kwargs):
        self.current_item.traces.append({"trace_type": "deployment", **kwargs})

    def trace_call(
        self, output: Optional[bytes], call_succeeded: bool, env: dict[str, Any], **kwargs
    ):
        python_args = kwargs.pop("python_args", None)
        function_name = kwargs.pop("function_name", None)

        if "calldata" in kwargs:
            kwargs["calldata"] = kwargs["calldata"].hex()

        self.current_item.traces.append(
            {
                "trace_type": "call",
                "output": None if output is None else output.hex(),
                "call_succeeded": call_succeeded,
                "env": env,
                "call_args": kwargs,
                "python_args": python_args,
                "function_name": function_name,
            }
        )

    def trace_set_balance(self, address: str, value: int):
        self.current_item.traces.append(
            {"trace_type": "set_balance", "address": address, "value": value}
        )

    def trace_clear_transient_storage(self):
        self.current_item.traces.append({"trace_type": "clear_transient_storage"})

    def finalize_export(self):
        for module_path, items in self.data.items():
            out = module_path.with_suffix(".json")
            out.parent.mkdir(parents=True, exist_ok=True)

            by_name = {
                item.name: {"deps": item.deps, "traces": item.traces, "item_type": item.item_type}
                for item in items
            }

            with out.open("w", encoding="utf-8") as fp:
                json.dump(by_name, fp, indent=2, sort_keys=True)
