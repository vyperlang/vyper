import textwrap
from dataclasses import dataclass, field
from typing import Optional

from vyper.venom.basicblock import IRLabel
from vyper.venom.function import IRFunction


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


class IRContext:
    functions: dict[IRLabel, IRFunction]
    ctor_mem_size: Optional[int]
    immutables_len: Optional[int]
    data_segment: list[DataSection]
    last_label: int

    def __init__(self) -> None:
        self.functions = {}
        self.ctor_mem_size = None
        self.immutables_len = None
        self.data_segment = []
        self.last_label = 0

    def add_function(self, fn: IRFunction) -> None:
        fn.ctx = self
        self.functions[fn.name] = fn

    def create_function(self, name: str) -> IRFunction:
        label = IRLabel(name, True)
        fn = IRFunction(label, self)
        self.add_function(fn)
        return fn

    def get_function(self, name: IRLabel) -> IRFunction:
        if name in self.functions:
            return self.functions[name]
        raise Exception(f"Function {name} not found in context")

    def get_next_label(self, suffix: str = "") -> IRLabel:
        if suffix != "":
            suffix = f"_{suffix}"
        self.last_label += 1
        return IRLabel(f"{self.last_label}{suffix}")

    def chain_basic_blocks(self) -> None:
        """
        Chain basic blocks together. This is necessary for the IR to be valid, and is done after
        the IR is generated.
        """
        for fn in self.functions.values():
            fn.chain_basic_blocks()

    def append_data_section(self, name: IRLabel) -> None:
        self.data_segment.append(DataSection(name))

    def append_data_item(self, data: IRLabel | bytes) -> None:
        """
        Append data to current data section
        """
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
