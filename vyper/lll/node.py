import inspect
import sys

from inflection import underscore as to_snake_case
from pyparsing import OneOrMore, nestedExpr

from typing import List, Tuple

from vyper.exceptions import CompilerPanic


class BaseNode:
    __slots__: Tuple[str, ...] = ("type",)
    type: str

    def __init__(self, *args):
        assert len(args) == len(self.__slots__), "Arg size mismatch"
        self.type = self.__class__.__name__.lower()
        assert self.type == args[0], f"Type should be {self.type}, not {args[0]}"
        # Skip first field (type)
        for attr, value in zip(self.__slots__[1:], args[1:]):
            # Non-iterable field
            if isinstance(value, str):
                try:
                    # Try to convert to hex
                    value = int(value, 16)
                    assert 0 <= value < 2 ** 256  # Must be a 256-bit unsigned integer
                except ValueError:
                    try:
                        # Try to convert to regular integer
                        value = setattr(self, attr, int(value))
                        assert 0 <= value < 2 ** 256  # Must be a 256-bit unsigned integer
                    except ValueError:
                        pass  # Should be text label
                finally:
                    # All three cases should work
                    setattr(self, attr, value)
            # Iterable field
            elif isinstance(value, list):
                if isinstance(value[0], str) and value[0] in NODES:
                    setattr(self, attr, NODES[value[0]](*value))
                else:
                    setattr(self, attr, value)
            # only iterable and non-iterable fields allowed
            else:
                raise CompilerPanic(f"'{self.type}' cannot handle '{attr}': {value}")

    @classmethod
    def parse(cls, program_string: str) -> "BaseNode":
        program = OneOrMore(nestedExpr()).parseString(program_string).asList()
        assert len(program) == 1, "Sanity check failed"
        program = program[0]  # PyParsing has extra nesting here for no reason
        if isinstance(program, list) and isinstance(program[0], str) and program[0] in NODES:
            # NOTE: People can do `cls.parse("""....""")` as a shortcut. This is here to make
            # sure if they choose a specific class (instead of BaseNode) that we obtain the
            # correct class from parsing
            if not issubclass(NODES[program[0]], cls):
                raise CompilerPanic(f"{program[0]} is not a subclass of {cls.__name__}")

            return NODES[program[0]](*program)  # Instantiate as `cls`
        else:
            raise CompilerPanic(f"Cannot handle program: {program}")

    def __str__(self) -> str:
        # TODO: Pretty print
        fields = " ".join(str(getattr(self, field)) for field in ["type"] + list(self.__slots__))
        return f"({fields})"


class Module(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "body")
    type: str
    body: List[BaseNode]


class Seq(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "body")
    type: str
    body: List[BaseNode]


class Def(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "name", "args", "body")
    type: str
    name: str
    args: List[str]
    body: List[BaseNode]


class Return(BaseNode):
    __slots__: Tuple[str, ...] = (
        "type",
        "body",
    )
    type: str
    body: List[BaseNode]


class When(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "condition", "body")
    type: str
    condition: BaseNode
    body: List[BaseNode]


class _BinOp(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "lhs", "rhs")
    type: str
    lhs: BaseNode
    rhs: BaseNode


class Eq(_BinOp):
    pass


class Ne(_BinOp):
    pass


class Caller(BaseNode):
    pass


class Panic(BaseNode):
    pass


class Continue(BaseNode):
    pass


class Break(BaseNode):
    pass


class Pass(BaseNode):
    pass


class If(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "condition", "positive", "negative")
    type: str
    condition: BaseNode
    positive: List[BaseNode]
    negative: List[BaseNode]


class Repeat(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "memory", "start", "rounds", "body")
    type: str
    memory: int
    start: int
    rounds: int
    body: List[BaseNode]


class Label(BaseNode):
    __slots__: Tuple[str, ...] = (
        "type",
        "name",
    )
    type: str
    name: str


class Goto(BaseNode):
    __slots__: Tuple[str, ...] = (
        "type",
        "label",
    )
    type: str
    label: str


class Sload(BaseNode):
    __slots__: Tuple[str, ...] = (
        "type",
        "register",
    )
    type: str
    register: int


class Sstore(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "register", "value")
    type: str
    register: int
    value: int


class Mload(BaseNode):
    __slots__: Tuple[str, ...] = (
        "type",
        "register",
    )
    type: str
    register: int


class Mstore(BaseNode):
    __slots__: Tuple[str, ...] = ("type", "register", "value")
    type: str
    register: int
    value: int


NODES = {
    to_snake_case(n): c
    for n, c in inspect.getmembers(sys.modules[__name__], inspect.isclass)
    if issubclass(c, BaseNode) and n != "BaseNode" and not n.startswith("_")
}

__all__ = [c.__name__ for c in NODES.values()]
