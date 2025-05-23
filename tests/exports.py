import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from pytest import FixtureDef, Item


# TODO what if the fixture as numeric suffix from user-code?
# we should use some specifc separator
def base_name(unique: str) -> str:
    # strip the numeric suffix we add when we re-instantiate: c2  ->  c
    i = len(unique)
    while i and unique[i - 1].isdigit():
        i -= 1
    return unique[:i]


def bucket_path_for(node: Union[FixtureDef, Item], test_root: Path, export_root: Path) -> Path:
    if isinstance(node, Item):
        mod_file = Path(node.module.__file__).resolve()
    else:  # FixtureDef
        mod_file = Path(sys.modules[node.func.__module__].__file__).resolve()
    return export_root / mod_file.relative_to(test_root)


@dataclass
class TracedItem:
    name: str
    deps: list[str]
    traces: list[dict[str, Any]]


class TestExporter:
    def __init__(self, export_dir: Path, test_root: Path):
        self.export_dir = export_dir
        self.test_root = test_root

        # session-wide state
        self.data: dict[Path, list[TracedItem]] = {}  # bucket → items
        self._counts: dict[tuple[Path, str], int] = {}  # (bucket,base_name)
        self._last_unique: dict[tuple[Path, str], str] = {}  # (bucket,base_name)
        self._executed_fixtures: list[str] = []  # [path/unique_name]

        # (id(fixturedef) -> (bucket_path, unique_name, will_execute))
        self._pending: dict[int, tuple[Path, str, bool]] = {}

        self._current_bucket: Optional[Path] = None

    @property
    def current_item(self) -> TracedItem:
        assert self._current_bucket, "set_item() not called yet"
        bucket = self.data[self._current_bucket]
        return bucket[-1]

    def set_item(self, node: Union[FixtureDef, Item], will_execute: bool = True):
        bucket = bucket_path_for(node, self.test_root, self.export_dir)
        lst = self.data.setdefault(bucket, [])
        self._current_bucket = bucket

        if isinstance(node, Item):
            lst.append(TracedItem(node.name, [], []))
            self._resolve_deps(node)
            return

        base = node.argname
        key = (bucket, base)

        if will_execute:
            cnt = self._counts.get(key, 0) + 1
            self._counts[key] = cnt
            unique = base if cnt == 1 else f"{base}{cnt}"
            lst.append(TracedItem(unique, [], []))
            self._last_unique[key] = unique
        else:  # fixture was cached from some previous run
            unique = self._last_unique[key]

        self._pending[id(node)] = (bucket, unique, will_execute)

        # resolve its own dependencies now (all required fixtures
        # already ran - guaranteed by pytest)
        if will_execute:
            self._resolve_deps(node)

    def finalize_item(self, node: Union[FixtureDef, Item]):
        # test items currently don't need any finalization
        if isinstance(node, Item):
            return

        bucket, unique, executed = self._pending.pop(id(node))
        lst = self.data[bucket]

        if not executed:  # cached call – already resolved
            return

        # The freshly added TracedItem is lst[-1]
        # this ordering is guaranteed by pytest
        ti = lst[-1]
        if not ti.traces:  # ran but produced no traces, discard
            lst.pop()
            return

        # record it so later nodes see the latest fixture instantiation
        self._executed_fixtures.append(str(bucket / unique))

    def _resolve_deps(self, node: Union[FixtureDef, Item]):
        wanted = set(node.fixturenames if isinstance(node, Item) else node.argnames)
        deps: list[str] = []

        # walk the executed list backwards – first match for every base wins
        # alternatively we could clear the fixtures, but this approach seems easier
        for ref in reversed(self._executed_fixtures):
            base = base_name(Path(ref).name)
            if base in wanted:
                deps.append(ref)
                wanted.remove(base)
                if not wanted:
                    break
        # `reversed(self._executed_fixtures)` iterates from newest to oldest
        # the oldest are the first executed, and we want to maintain the
        # execution order
        self.current_item.deps = list(reversed(deps))

    def trace_deployment(self, **kwargs):
        self.current_item.traces.append({"trace_type": "deployment", **kwargs})

    def trace_call(self, output: Optional[bytes], **call_args):
        if "calldata" in call_args:
            call_args["calldata"] = call_args["calldata"].hex()
        self.current_item.traces.append(
            {
                "trace_type": "call",
                "output": None if output is None else output.hex(),
                "call_args": call_args,
            }
        )

    def finalize_export(self):
        for bucket, traced_items in self.data.items():
            json_path = bucket.with_suffix(".json")
            json_path.parent.mkdir(parents=True, exist_ok=True)

            with json_path.open("w", encoding="utf-8") as fp:
                json.dump([ti.__dict__ for ti in traced_items], fp, indent=2, sort_keys=True)
