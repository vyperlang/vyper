from dataclasses import dataclass
from typing import Any, TypeVar

from vyper.evm.opcodes import get_opcodes, version_check
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet

PUSH_OFFSET = 0x5F
DUP_OFFSET = 0x7F
SWAP_OFFSET = 0x8F

T = TypeVar("T")

def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


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


@dataclass
class DataHeader:
    label: Label

    def __repr__(self):
        return f"DATA {self.label.label}"


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


class BaseConstOp:
    def __init__(self, name: str, op1: str | int, op2: str | int):
        assert isinstance(name, str)
        assert isinstance(op1, (str, int))
        assert isinstance(op2, (str, int))
        self.name = name
        self.op1 = op1
        self.op2 = op2

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        return self.name == other.name and self.op1 == other.op1 and self.op2 == other.op2

    def _resolve_operand(self, operand: str | int, symbol_map: dict[T, int]) -> int | None:
        if isinstance(operand, str):
            op_ref = CONSTREF(operand)
            if op_ref in symbol_map:
                return symbol_map[op_ref]
        elif isinstance(operand, int):
            return operand
        return None

    def calculate(self, symbol_map: dict[CONSTREF, int]) -> int | None:
        op1_val = self._resolve_operand(self.op1, symbol_map)
        op2_val = self._resolve_operand(self.op2, symbol_map)

        if op1_val is not None and op2_val is not None:
            return self._apply_operation(op1_val, op2_val)
        return None

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        raise NotImplementedError("Subclasses must implement _apply_operation")


class CONST_ADD(BaseConstOp):
    def __repr__(self):
        return f"CONST_ADD {self.name} {self.op1} {self.op2}"

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        return op1_val + op2_val


class CONST_MAX(BaseConstOp):
    def __repr__(self):
        return f"CONST_MAX {self.name} {self.op1} {self.op2}"

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        return max(op1_val, op2_val)


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
    return [PUSHLABEL(label), "JUMP"]


def JUMPI(label: Label):
    return [PUSHLABEL(label), "JUMPI"]


def mkdebug(pc_debugger, ast_source):
    # compile debug instructions
    # (this is dead code -- CMC 2025-05-08)
    i = TaggedInstruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


def is_symbol(i):
    return isinstance(i, Label)


def is_ofst(assembly_item):
    return isinstance(assembly_item, PUSH_OFST)


AssemblyInstruction = (
    str | TaggedInstruction | int | PUSHLABEL | Label | PUSH_OFST | DATA_ITEM | DataHeader | CONST
)

def _add_to_symbol_map(symbol_map: dict[T, int], item: T, value: int):
    if item in symbol_map:  # pragma: nocover
        raise CompilerPanic(f"duplicate label: {item}")
    symbol_map[item] = value


def _resolve_constants(
    assembly: list[AssemblyInstruction], symbol_map: dict[T, int]
):
    for item in assembly:
        if isinstance(item, CONST):
            _add_to_symbol_map(symbol_map, CONSTREF(item.name), item.value)

    while True:
        changed = False
        for item in assembly:
            if isinstance(item, (CONST_ADD, CONST_MAX)):
                # Skip if this constant is already resolved
                if CONSTREF(item.name) in symbol_map:
                    continue

                # Calculate the value if possible
                if (value := item.calculate(symbol_map)) is not None:
                    _add_to_symbol_map(symbol_map, CONSTREF(item.name), value)
                    changed = True

        if not changed:
            break

def resolve_symbols(
    assembly: list[AssemblyInstruction],
) -> tuple[dict[Label, int], dict[CONSTREF, int], dict[str, Any]]:
    """
    Construct symbol map from assembly list

    Returns:
        symbol_map: dict from labels to values
        source_map: source map dict that gets output for the user
    """
    source_map: dict[str, Any] = {
        "breakpoints": OrderedSet(),
        "pc_breakpoints": OrderedSet(),
        "pc_jump_map": {0: "-"},
        "pc_raw_ast_map": {},
        "error_map": {},
    }

    symbol_map: dict[Label, int] = {}

    pc: int = 0

    _resolve_constants(assembly, symbol_map)

    # resolve labels (i.e. JUMPDEST locations) to actual code locations,
    # and simultaneously build the source map.
    for i, item in enumerate(assembly):
        # add it to the source map
        note_line_num(source_map, pc, item)

        # update pc_jump_map
        if item == "JUMP":
            last = assembly[i - 1]
            if isinstance(last, PUSHLABEL) and last.label.label.startswith("internal"):
                if last.label.label.endswith("cleanup"):
                    # exit an internal function
                    source_map["pc_jump_map"][pc] = "o"
                else:
                    # enter an internal function
                    source_map["pc_jump_map"][pc] = "i"
            else:
                # everything else
                source_map["pc_jump_map"][pc] = "-"
        elif item in ("JUMPI", "JUMPDEST"):
            source_map["pc_jump_map"][pc] = "-"

        if item == "DEBUG":
            continue  # "debug" opcode does not go into bytecode

        if isinstance(item, CONST):
            continue  # CONST declarations do not go into bytecode

        # update pc
        if isinstance(item, Label):
            _add_to_symbol_map(symbol_map, item, pc)
            pc += 1  # jumpdest

        elif isinstance(item, DataHeader):
            # Don't increment pc as the symbol itself doesn't go into code
            _add_to_symbol_map(symbol_map, item.label, pc)

        elif isinstance(item, PUSHLABEL):
            pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits

        elif isinstance(item, PUSH_OFST):
            assert isinstance(item.ofst, int), item
            # [PUSH_OFST, (Label foo), bar] -> PUSH2 (foo+bar)
            # [PUSH_OFST, _mem_foo, bar] -> PUSHN (foo+bar)
            if isinstance(item.label, Label):
                pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
            elif isinstance(item.label, CONSTREF):
                const = symbol_map[item.label]
                val = const + item.ofst
                pc += calc_push_size(val)
            else:  # pragma: nocover
                raise CompilerPanic(f"invalid ofst {item.label}")

        elif isinstance(item, DATA_ITEM):
            if isinstance(item.data, Label):
                pc += SYMBOL_SIZE
            else:
                assert isinstance(item.data, bytes)
                pc += len(item.data)
        elif isinstance(item, int):
            assert 0 <= item < 256
            pc += 1
        else:
            assert isinstance(item, str) and item in get_opcodes(), item
            pc += 1

    source_map["breakpoints"] = list(source_map["breakpoints"])
    source_map["pc_breakpoints"] = list(source_map["pc_breakpoints"])

    # magic -- probably the assembler should actually add this label
    _add_to_symbol_map(symbol_map, Label("code_end"), pc)

    return symbol_map, source_map


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


def note_line_num(line_number_map, pc, item):
    # Record AST attached to pc
    if isinstance(item, TaggedInstruction):
        if (ast_node := item.ast_source) is not None:
            ast_node = ast_node.get_original_node()
            if hasattr(ast_node, "node_id"):
                line_number_map["pc_raw_ast_map"][pc] = ast_node

        if item.error_msg is not None:
            line_number_map["error_map"][pc] = item.error_msg

    note_breakpoint(line_number_map, pc, item)


def note_breakpoint(line_number_map, pc, item):
    # Record line number attached to pc
    if item == "DEBUG":
        # Is PC debugger, create PC breakpoint.
        if item.pc_debugger:
            line_number_map["pc_breakpoints"].add(pc)
        # Create line number breakpoint.
        else:
            line_number_map["breakpoints"].add(item.lineno + 1)


SYMBOL_SIZE = 2  # size of a PUSH instruction for a code symbol


# predict what length of an assembly [data] node will be in bytecode
def get_data_segment_lengths(assembly: list[AssemblyInstruction]) -> list[int]:
    ret = []
    for item in assembly:
        if isinstance(item, DataHeader):
            ret.append(0)
            continue
        if len(ret) == 0:
            # haven't yet seen a data header
            continue
        assert isinstance(item, DATA_ITEM)
        if is_symbol(item.data):
            ret[-1] += SYMBOL_SIZE
        elif isinstance(item.data, bytes):
            ret[-1] += len(item.data)
        else:  # pragma: nocover
            raise ValueError(f"invalid data {type(item)} {item}")

    return ret


def _compile_data_item(item: DATA_ITEM, symbol_map: dict[Label, int]) -> bytes:
    if isinstance(item.data, bytes):
        return item.data
    if isinstance(item.data, Label):
        symbolbytes = symbol_map[item.data].to_bytes(SYMBOL_SIZE, "big")
        return symbolbytes

    raise CompilerPanic(f"Invalid data {type(item.data)}, {item.data}")  # pragma: nocover


# helper function
def _compile_push_instruction(assembly: list[AssemblyInstruction]) -> bytes:
    push_mnemonic = assembly[0]
    assert isinstance(push_mnemonic, str) and push_mnemonic.startswith("PUSH")
    push_instr = PUSH_OFFSET + int(push_mnemonic[4:])
    ret = [push_instr]

    for item in assembly[1:]:
        assert isinstance(item, int)
        ret.append(item)
    return bytes(ret)


def assembly_to_evm(assembly: list[AssemblyInstruction]) -> tuple[bytes, dict[str, Any]]:
    """
    Generate bytecode and source map from assembly

    Returns:
        bytecode: bytestring of the EVM bytecode
        source_map: source map dict that gets output for the user
    """
    # This API might seem a bit strange, but it's backwards compatible
    symbol_map, source_map = resolve_symbols(assembly)
    bytecode = _assembly_to_evm(assembly, symbol_map)
    return bytecode, source_map


def _assembly_to_evm(
    assembly: list[AssemblyInstruction],
    symbol_map: dict[Label, int],
) -> bytes:
    """
    Assembles assembly into EVM bytecode

    Parameters:
        assembly: list of asm instructions
        symbol_map: dict from labels to resolved locations in the code

    Returns: bytes representing the bytecode
    """
    ret = bytearray()

    # now that all symbols have been resolved, generate bytecode
    # using the symbol map
    for item in assembly:
        if item in ("DEBUG",):
            continue  # skippable opcodes
        elif isinstance(item, CONST):
            continue  # CONST things do not show up in bytecode
        elif isinstance(item, DataHeader):
            continue  # DataHeader does not show up in bytecode

        elif isinstance(item, PUSHLABEL):
            # push a symbol to stack
            label = item.label
            bytecode = _compile_push_instruction(PUSH_N(symbol_map[label], n=SYMBOL_SIZE))
            ret.extend(bytecode)

        elif isinstance(item, Label):
            jumpdest_opcode = get_opcodes()["JUMPDEST"][0]
            assert jumpdest_opcode is not None  # help mypy
            ret.append(jumpdest_opcode)

        elif isinstance(item, PUSH_OFST):
            # PUSH_OFST (LABEL foo) 32
            # PUSH_OFST (const foo) 32
            if isinstance(item.label, Label):
                ofst = symbol_map[item.label] + item.ofst
                bytecode = _compile_push_instruction(PUSH_N(ofst, SYMBOL_SIZE))
            else:
                assert isinstance(item.label, CONSTREF)
                ofst = symbol_map[item.label] + item.ofst
                bytecode = _compile_push_instruction(PUSH(ofst))

            ret.extend(bytecode)

        elif isinstance(item, int):
            ret.append(item)
        elif isinstance(item, str) and item.upper() in get_opcodes():
            opcode = get_opcodes()[item.upper()][0]
            # TODO: fix signature of get_opcodes()
            assert opcode is not None  # help mypy
            ret.append(opcode)
        elif isinstance(item, DATA_ITEM):
            ret.extend(_compile_data_item(item, symbol_map))
        elif item[:4] == "PUSH":
            ret.append(PUSH_OFFSET + int(item[4:]))
        elif item[:3] == "DUP":
            ret.append(DUP_OFFSET + int(item[3:]))
        elif item[:4] == "SWAP":
            ret.append(SWAP_OFFSET + int(item[4:]))
        else:  # pragma: no cover
            # unreachable
            raise ValueError(f"Weird symbol in assembly: {type(item)} {item}")

    return bytes(ret)
