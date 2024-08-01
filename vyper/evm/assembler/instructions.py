from dataclasses import dataclass

from vyper.evm.assembler.symbols import CONST, CONSTREF, Label
from vyper.evm.opcodes import version_check


@dataclass
class JUMPDEST:
    label: Label

    def __repr__(self) -> str:
        return f"JUMPDEST {self.label.label}"


@dataclass(frozen=True)
class PUSHLABEL:
    label: Label

    def __repr__(self) -> str:
        return f"PUSHLABEL {self.label.label}"


@dataclass(frozen=True)
class PUSHLABELJUMPDEST:
    """
    This is a special case of PUSHLABEL that is used to push a label
    that is used in a jump or return address. This is used to allow
    the optimizer to remove jumpdests that are not used.
    """

    label: Label

    def __repr__(self) -> str:
        return f"PUSHLABELJUMPDEST {self.label.label}"


# push the result of an addition (which might be resolvable at compile-time)
@dataclass(frozen=True)
class PUSH_OFST:
    label: Label | CONSTREF
    ofst: int

    def __repr__(self) -> str:
        # Both Label and CONSTREF have a .label attribute that is a string
        label_str = self.label.label
        return f"PUSH_OFST({label_str}, {self.ofst})"


@dataclass
class PC_RESET:
    """
    Special instruction to reset PC counter for runtime code sections.
    This allows jump destinations within the section to be calculated
    relative to the reset point rather than absolute positions.
    """
    value: int = 0  # The value to reset PC to (usually 0)

    def __repr__(self) -> str:
        return f"PC_RESET {self.value}"


@dataclass
class DATA_ITEM:
    data: bytes | Label

    def __repr__(self) -> str:
        if isinstance(self.data, bytes):
            return f"DATABYTES {self.data.hex()}"
        elif isinstance(self.data, Label):
            return f"DATALABEL {self.data.label}"


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


# a string (assembly instruction) but with additional metadata from the source code
class TaggedInstruction(str):
    def __new__(cls, sstr, *args, **kwargs):
        return super().__new__(cls, sstr)

    def __init__(self, _sstr, ast_source=None, error_msg=None):
        self.error_msg = error_msg
        self.pc_debugger = False
        self.ast_source = ast_source


def PUSH(x):
    bs = num_to_bytearray(x)
    # starting in shanghai, can do push0 directly with no immediates
    if len(bs) == 0 and not version_check(begin="shanghai"):
        bs = [0]
    return [f"PUSH{len(bs)}"] + bs


# push an exact number of bytes
def PUSH_N(x, n):
    o = []
    for _i in range(n):
        o.insert(0, x % 256)
        x //= 256
    assert x == 0
    return [f"PUSH{len(o)}"] + o


def JUMP(label: Label):
    return [PUSHLABELJUMPDEST(label), "JUMP"]


def JUMPI(label: Label):
    return [PUSHLABELJUMPDEST(label), "JUMPI"]


def mkdebug(pc_debugger, ast_source):
    # compile debug instructions
    # (this is dead code -- CMC 2025-05-08)
    i = TaggedInstruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


AssemblyInstruction = (
    str
    | TaggedInstruction
    | int
    | Label
    | PUSHLABEL
    | PUSHLABELJUMPDEST
    | JUMPDEST
    | PUSH_OFST
    | DATA_ITEM
    | CONST
)
