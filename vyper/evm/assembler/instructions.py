from dataclasses import dataclass

from vyper.evm.opcodes import version_check


class Label:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"LABEL {self.label}"

    def __eq__(self, other):
        if not isinstance(other, Label):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


def is_label(i):
    return isinstance(i, Label)


# this could be fused with Label, the only difference is if
# it gets looked up from const_map or symbol_map.
class CONSTREF:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"CONSTREF {self.label}"

    def __eq__(self, other):
        if not isinstance(other, CONSTREF):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


@dataclass
class DataHeader:
    label: Label

    def __repr__(self):
        return f"DATA {self.label.label}"


class DATA_ITEM:
    def __init__(self, item: bytes | Label):
        self.data = item

    def __repr__(self):
        if isinstance(self.data, bytes):
            return f"DATABYTES {self.data.hex()}"
        elif isinstance(self.data, Label):
            return f"DATALABEL {self.data.label}"


# a string (assembly instruction) but with additional metadata from the source code
class TaggedInstruction(str):
    def __new__(cls, sstr, *args, **kwargs):
        return super().__new__(cls, sstr)

    def __init__(self, sstr, ast_source=None, error_msg=None):
        self.error_msg = error_msg
        self.pc_debugger = False

        self.ast_source = ast_source


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


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


# Calculate the size of PUSH instruction
def calc_push_size(val: int):
    # stupid implementation. this is "slow", but its correctness is
    # obvious verify, as opposed to
    # ```
    # (val.bit_length() + 7) // 8
    #    + (1
    #         if (val > 0 or version_check(begin="shanghai"))
    #      else 0)
    # ```
    return len(PUSH(val))


class CONST:
    def __init__(self, name: str, value: int):
        assert isinstance(name, str)
        assert isinstance(value, int)
        self.name = name
        self.value = value

    def __repr__(self):
        return f"CONST {self.name} {self.value}"

    def __eq__(self, other):
        if not isinstance(other, CONST):
            return False
        return self.name == other.name and self.value == other.value


class PUSHLABEL:
    def __init__(self, label: Label):
        assert isinstance(label, Label), label
        self.label = label

    def __repr__(self):
        return f"PUSHLABEL {self.label.label}"

    def __eq__(self, other):
        if not isinstance(other, PUSHLABEL):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


# push the result of an addition (which might be resolvable at compile-time)
class PUSH_OFST:
    def __init__(self, label: Label | CONSTREF, ofst: int):
        # label can be Label or CONSTREF
        assert isinstance(label, (Label, CONSTREF))
        self.label = label
        self.ofst = ofst

    def __repr__(self):
        label = self.label
        if isinstance(label, Label):
            label = label.label  # str
        return f"PUSH_OFST({label}, {self.ofst})"

    def __eq__(self, other):
        if not isinstance(other, PUSH_OFST):
            return False
        return self.label == other.label and self.ofst == other.ofst

    def __hash__(self):
        return hash((self.label, self.ofst))


def JUMP(label: Label):
    return [PUSHLABEL(label), "JUMP"]


def JUMPI(label: Label):
    return [PUSHLABEL(label), "JUMPI"]


def mkdebug(pc_debugger, ast_source):
    # compile debug instructions
    # (this is dead code -- CMC 2025-05-08)
    i = TaggedInstruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


AssemblyInstruction = (
    str | TaggedInstruction | int | PUSHLABEL | Label | PUSH_OFST | DATA_ITEM | DataHeader | CONST
)
