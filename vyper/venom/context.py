import textwrap
from dataclasses import dataclass, field
from typing import Iterator, Optional

from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable
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
    entry_function: Optional[IRFunction]
    constants: dict[str, int]  # globally defined constants
    data_segment: list[DataSection]
    last_label: int
    last_variable: int

    def __init__(self) -> None:
        self.functions = {}
        self.entry_function = None
        self.data_segment = []
        self.constants = {}

        self.last_label = 0
        self.last_variable = 0

    def get_basic_blocks(self) -> Iterator[IRBasicBlock]:
        for fn in self.functions.values():
            for bb in fn.get_basic_blocks():
                yield bb

    def add_function(self, fn: IRFunction) -> None:
        fn.ctx = self
        self.functions[fn.name] = fn

    def remove_function(self, fn: IRFunction) -> None:
        del self.functions[fn.name]

    def create_function(self, name: str) -> IRFunction:
        label = IRLabel(name, True)
        assert label not in self.functions, f"duplicate function {label}"
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
        if suffix != "":
            suffix = f"_{suffix}"
        self.last_label += 1
        return IRLabel(f"{self.last_label}{suffix}")

    def get_next_variable(self) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}")

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def append_data_section(self, name: IRLabel) -> None:
        self.data_segment.append(DataSection(name))

    def append_data_item(self, data: IRLabel | bytes) -> None:
        """
        Append data to current data section
        """
        assert len(self.data_segment) > 0
        data_section = self.data_segment[-1]
        data_section.data_items.append(DataItem(data))

    def add_constant(self, name: str, value: int) -> None:
        assert name not in self.constants
        self.constants[name] = value

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
