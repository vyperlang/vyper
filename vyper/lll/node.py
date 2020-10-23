import inspect
import sys

from pyparsing import OneOrMore, nestedExpr

from typing import List, Tuple, Union

from vyper.exceptions import CompilerPanic


def is_hex(value: str) -> bool:
    return value[:2] == "0x" and all(n.lower() in "0123456789abcdef" for n in value[2:])


def is_num(value: str) -> bool:
    return all(n.lower() in "0123456789" for n in value)


def convert_value(value: str) -> Union[str, int]:
    if is_hex(value):
        # Try to convert to hex
        v = int(value.strip("0x"), 16)

        if 0 > v or v >= 2 ** 256:
            raise CompilerPanic("Must be a 256-bit unsigned integer")

        return v

    elif is_num(value):
        # Try to convert to regular integer
        v = int(value)

        if 0 > v or v >= 2 ** 256:
            raise CompilerPanic("Must be a 256-bit unsigned integer")

        return v

    elif value in NODES:
        raise CompilerPanic("Restricted keyword")

    else:
        return value


class BaseNode:
    __slots__: Tuple[str, ...] = ()

    def __init__(self, *args: Union[List, str]):
        type = self.__class__.__name__.lower()
        if type not in NODES:
            raise CompilerPanic(f"Cannot instantiate '{self.__class__.__name__}' directly")

        if len(args) != len(self.__slots__):
            raise CompilerPanic(
                f"Arg size mismatch for '{type}': '{len(self.__slots__)}' != '{len(args)}'"
            )

        for attr, value in zip(self.__slots__, args):
            # Non-iterable field
            if isinstance(value, str):
                setattr(self, attr, convert_value(value))

            # Iterable field
            elif isinstance(value, list):
                if len(value) > 0 and isinstance(value[0], str) and value[0] in NODES:
                    # A node class
                    setattr(self, attr, NODES[value[0]](*value[1:]))
                elif isinstance(value, list) and all(
                    isinstance(v, list) and v[0] in NODES for v in value
                ):
                    # A list of nodes
                    body = tuple(NODES[v[0]](*v[1:]) for v in value)
                    setattr(self, attr, body)
                elif isinstance(value, list) and all(isinstance(v, str) for v in value):
                    # A list of strings and/or numbers
                    setattr(self, attr, tuple(convert_value(v) for v in value))
                else:
                    raise CompilerPanic(f"'{type}' cannot handle '{attr}': {value}")

            # only iterable and non-iterable fields allowed
            else:
                raise CompilerPanic(f"'{type}' cannot handle '{attr}': {value}")

    @classmethod
    def parse(cls, program_string: str) -> "BaseNode":
        # TODO Remove pyparsing (or replace /w SLY)
        program = OneOrMore(nestedExpr()).parseString(program_string).asList()
        assert len(program) == 1, "Sanity check failed"
        program = program[0]  # PyParsing has extra nesting here for no reason

        if (
            not isinstance(program, list)
            or not isinstance(program[0], str)
            or not program[0] in NODES
        ):
            raise CompilerPanic(f"Cannot handle program: {program}")
        else:
            return NODES[program[0]](*program[1:])  # Instantiate as `cls`

    def __str__(self) -> str:
        # TODO: Pretty print
        fields = (getattr(self, field) for field in self.__slots__)
        fields = (
            "(" + " ".join(str(i) for i in f) + ")" if isinstance(f, tuple) else str(f)
            for f in fields
        )
        return "(" + " ".join((self.__class__.__name__.lower(), *fields)) + ")"


class Module(BaseNode):
    __slots__: Tuple[str, ...] = ("body",)
    body: List[BaseNode]


class Seq(BaseNode):
    __slots__: Tuple[str, ...] = ("body",)
    body: List[BaseNode]


class Def(BaseNode):
    __slots__: Tuple[str, ...] = ("name", "args", "body")
    name: str
    args: List[str]
    body: List[BaseNode]


class Return(BaseNode):
    __slots__: Tuple[str, ...] = ("body",)
    body: List[BaseNode]


class When(BaseNode):
    __slots__: Tuple[str, ...] = ("condition", "body")
    condition: BaseNode
    body: List[BaseNode]


class _UnaryOp(BaseNode):
    __slots__: Tuple[str, ...] = ("node",)
    node: BaseNode


class IsZero(_UnaryOp):
    pass


class Not(_UnaryOp):
    pass


class _BinOp(BaseNode):
    __slots__: Tuple[str, ...] = ("lhs", "rhs")
    lhs: BaseNode
    rhs: BaseNode


class Eq(_BinOp):
    pass


class Ne(_BinOp):
    pass


class Shr(_BinOp):
    pass


class Slt(_BinOp):
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
    __slots__: Tuple[str, ...] = ("condition", "positive", "negative")
    condition: BaseNode
    positive: List[BaseNode]
    negative: List[BaseNode]


class Repeat(BaseNode):
    __slots__: Tuple[str, ...] = ("memory", "start", "rounds", "body")
    memory: int
    start: int
    rounds: int
    body: List[BaseNode]


class Label(BaseNode):
    __slots__: Tuple[str, ...] = ("name",)
    name: str


class Goto(BaseNode):
    __slots__: Tuple[str, ...] = ("label",)
    label: str


class Sload(BaseNode):
    __slots__: Tuple[str, ...] = ("slot",)
    register: int


class Sstore(BaseNode):
    __slots__: Tuple[str, ...] = ("slot", "value")
    register: int
    value: int


class Mload(BaseNode):
    __slots__: Tuple[str, ...] = ("register",)
    register: int


class Mstore(BaseNode):
    __slots__: Tuple[str, ...] = ("register", "value")
    register: int
    value: int


class Codeload(BaseNode):
    __slots__: Tuple[str, ...] = ("length",)
    length: int


class Codecopy(BaseNode):
    __slots__: Tuple[str, ...] = ("slot", "length", "size")
    slot: int
    length: int
    size: int


NODES = {
    n.lower(): c
    for n, c in inspect.getmembers(sys.modules[__name__], inspect.isclass)
    if issubclass(c, BaseNode) and n != "BaseNode" and not n.startswith("_")
}

__all__ = [c.__name__ for c in NODES.values()]
