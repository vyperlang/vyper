import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator, Optional

from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
from vyper.venom.function import IRFunction
from vyper.venom.memory_allocator import MemoryAllocator

if TYPE_CHECKING:
    from vyper.venom.analysis.analysis import IRGlobalAnalysesCache


@dataclass
class DataItem:
    data: IRLabel | bytes  # can be raw data or bytes

    def __str__(self):
        if isinstance(self.data, IRLabel):
            return f"@{self.data}"
        else:
            assert isinstance(self.data, bytes)
            return f'x"{self.data.hex()}"'


@dataclass
class DataSection:
    label: IRLabel
    data_items: list[DataItem] = field(default_factory=list)

    def __str__(self):
        ret = [f"dbsection {self.label.value}:"]
        for item in self.data_items:
            ret.append(f"  db {item}")
        return "\n".join(ret)


@dataclass
class DeployInfo:
    runtime_codesize: int
    immutables_len: int


class IRContext:
    functions: dict[IRLabel, IRFunction]
    entry_function: Optional[IRFunction]
    data_segment: list[DataSection]
    last_label: int
    last_variable: int
    mem_allocator: MemoryAllocator
    global_analyses_cache: Optional["IRGlobalAnalysesCache"]
    prefix: str

    def __init__(self, prefix: str = "") -> None:
        self.functions = {}
        self.entry_function = None
        self.data_segment = []

        self.last_label = 0
        self.last_variable = 0

        self.mem_allocator = MemoryAllocator()
        self.global_analyses_cache = None
        self.prefix = prefix

    def get_basic_blocks(self) -> Iterator[IRBasicBlock]:
        for fn in self.functions.values():
            for bb in fn.get_basic_blocks():
                yield bb

    def _namespaced_value(self, value: str) -> str:
        return f"{self.prefix}.{value}" if self.prefix else value

    def add_function(self, fn: IRFunction) -> None:
        assert fn.name not in self.functions, f"duplicate function {fn.name}"
        fn.ctx = self
        self.functions[fn.name] = fn

    def remove_function(self, fn: IRFunction) -> None:
        del self.functions[fn.name]

    def named_label(self, name: str, is_symbol: bool = True) -> IRLabel:
        """Return ``IRLabel(f"{prefix}.{name}")`` (or ``IRLabel(name)`` if
        prefix is empty).  Use for labels that must survive a :meth:`merge`.
        """
        return IRLabel(self._namespaced_value(name), is_symbol=is_symbol)

    def create_function(self, name: str) -> IRFunction:
        label = self.named_label(name, is_symbol=True)
        fn = IRFunction(label, self)
        self.add_function(fn)
        return fn

    def get_function(self, name: IRLabel) -> IRFunction:
        if name in self.functions:
            return self.functions[name]
        raise Exception(f"Function {name} not found in context")

    def get_functions(self) -> Iterator[IRFunction]:
        return iter(self.functions.values())

    def get_next_label(self, suffix: str = "") -> IRLabel:
        suffix = f"_{suffix}" if suffix else ""
        self.last_label += 1
        return IRLabel(self._namespaced_value(f"{self.last_label}{suffix}"))

    def get_next_variable(self) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}")

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def append_data_section(self, name: IRLabel | str) -> None:
        """``str`` → auto-namespaced via :meth:`named_label`; ``IRLabel`` → used as-is."""
        if isinstance(name, str):
            name = self.named_label(name)
        self.data_segment.append(DataSection(name))

    def merge(self, *sources: "IRContext") -> "IRContext":
        """Splice each source's functions / data sections into ``self``; clears
        the sources.  Raises :class:`ValueError` on label clash before mutating.
        """
        function_labels = set(self.functions)
        data_labels = {section.label for section in self.data_segment}
        bb_labels = {bb.label for bb in self.get_basic_blocks()}

        for src in sources:
            for fn in src.functions.values():
                if fn.name in function_labels:
                    raise ValueError(
                        f"merge: duplicate function label {fn.name}; "
                        "two sources share a prefix or collide with the target"
                    )
                function_labels.add(fn.name)

                for bb in fn.get_basic_blocks():
                    if bb.label in bb_labels:
                        raise ValueError(
                            f"merge: duplicate basic block label {bb.label}; "
                            "two sources share a prefix or collide with the target"
                        )
                    bb_labels.add(bb.label)

            for section in src.data_segment:
                if section.label in data_labels:
                    raise ValueError(
                        f"merge: duplicate data section label {section.label}; "
                        "two sources share a prefix or collide with the target"
                    )
                data_labels.add(section.label)

        for src in sources:
            for fn in list(src.functions.values()):
                self.add_function(fn)
            self.data_segment.extend(src.data_segment)
            src.functions.clear()
            src.data_segment.clear()
            src.entry_function = None
        return self

    def append_data_item(self, data: IRLabel | bytes | str) -> None:
        """
        Append data to current data section
        """
        if isinstance(data, str):
            data = self.named_label(data)
        assert len(self.data_segment) > 0
        data_section = self.data_segment[-1]
        data_section.data_items.append(DataItem(data))

    def as_graph(self) -> str:
        s = ["digraph G {"]
        for fn in self.functions.values():
            s.append(fn.as_graph(True))
            s.append("\n")
        s.append("}")
        return "\n".join(s)

    def __repr__(self) -> str:
        s = []
        for fn in self.functions.values():
            s.append(IRFunction.__repr__(fn))
            s.append("\n")

        if len(self.data_segment) > 0:
            s.append("data readonly {")
            for data_section in self.data_segment:
                s.append(textwrap.indent(DataSection.__str__(data_section), "  "))
            s.append("}")

        return "\n".join(s)
