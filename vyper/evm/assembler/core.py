from typing import Any

from vyper.evm.assembler.constants import DUP_OFFSET, PUSH_OFFSET, SWAP_OFFSET
from vyper.evm.assembler.symbols import CONST, CONSTREF, BaseConstOp, Label, SymbolKey
from vyper.evm.opcodes import get_opcodes, version_check
from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet


def num_to_bytearray(x):
    o = []
    while x > 0:
        o.insert(0, x % 256)
        x //= 256
    return o


class JUMPDEST:
    def __init__(self, label: Label):
        assert isinstance(label, Label), label
        self.label = label

    def __repr__(self):
        return f"JUMPDEST {self.label.label}"


class PUSHLABEL:
    def __init__(self, label: Label):
        assert isinstance(label, Label), f"invalid label {type(label)} {label}"
        self.label = label

    def __repr__(self):
        return f"PUSHLABEL {self.label.label}"

    def __eq__(self, other):
        if not isinstance(other, PUSHLABEL):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)


class PUSHLABELJUMPDEST:
    """
    This is a special case of PUSHLABEL that is used to push a label
    that is used in a jump or return address. This is used to allow
    the optimizer to remove jumpdests that are not used.
    """

    def __init__(self, label: Label):
        assert isinstance(label, Label), label
        self.label = label

    def __repr__(self):
        return f"PUSHLABELJUMPDEST {self.label.label}"

    def __eq__(self, other):
        if not isinstance(other, PUSHLABELJUMPDEST):
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
    return [PUSHLABELJUMPDEST(label), "JUMP"]


def JUMPI(label: Label):
    return [PUSHLABELJUMPDEST(label), "JUMPI"]


def mkdebug(pc_debugger, ast_source):
    # compile debug instructions
    # (this is dead code -- CMC 2025-05-08)
    i = TaggedInstruction("DEBUG", ast_source)
    i.pc_debugger = pc_debugger
    return [i]


def is_label(i):
    """Check if an item is a Label instance."""
    return isinstance(i, Label)


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


def _add_to_symbol_map(symbol_map: dict[SymbolKey, int], item: SymbolKey, value: int):
    if item in symbol_map:  # pragma: nocover
        raise CompilerPanic(f"duplicate label: {item}")
    symbol_map[item] = value


def _resolve_constants(
    assembly: list[AssemblyInstruction], symbol_map: dict[SymbolKey, int]
) -> set[str]:
    """
    Resolve constant values and track which constants depend on labels.

    Returns:
        Set of constant names that depend on labels (directly or indirectly)
    """
    label_dependent_consts: set[str] = set()

    # First, add simple CONST declarations
    for item in assembly:
        if isinstance(item, CONST):
            _add_to_symbol_map(symbol_map, CONSTREF(item.name), item.value)

    # Track which constants reference labels (we'll check this later after labels are positioned)
    # For now, just identify constants that have string operands that might be labels
    # Collect all constant names first (including those from CONST declarations)
    all_const_names = set()
    for item in assembly:
        if isinstance(item, CONST):
            all_const_names.add(item.name)
        elif isinstance(item, BaseConstOp):
            all_const_names.add(item.name)

    for item in assembly:
        if isinstance(item, BaseConstOp):
            # Check if any operand is a string that could be a label
            for operand in [item.op1, item.op2]:
                if isinstance(operand, str):
                    # Check if it's not a known constant name
                    if operand not in all_const_names:
                        # This could be a label reference
                        label_dependent_consts.add(item.name)

    max_iterations = 100  # Prevent infinite loops from circular dependencies
    iterations = 0

    while iterations < max_iterations:
        changed = False
        for item in assembly:
            if isinstance(item, BaseConstOp):
                # Skip if this constant is already resolved
                if CONSTREF(item.name) in symbol_map:
                    continue

                # Skip if this is a label-dependent constant
                if item.name in label_dependent_consts:
                    continue

                # Check if this constant depends on other label-dependent constants
                depends_on_label = False
                for operand in [item.op1, item.op2]:
                    if isinstance(operand, str) and operand in label_dependent_consts:
                        label_dependent_consts.add(item.name)
                        depends_on_label = True
                        break

                if depends_on_label:
                    continue

                # Calculate the value if possible
                if (value := item.calculate(symbol_map)) is not None:
                    _add_to_symbol_map(symbol_map, CONSTREF(item.name), value)
                    changed = True

        if not changed:
            break

        iterations += 1

    # Check if we hit the iteration limit (circular dependency)
    if iterations >= max_iterations:
        unresolved = []
        for item in assembly:
            if isinstance(item, BaseConstOp) and CONSTREF(item.name) not in symbol_map:
                # Only report non-label-dependent constants as unresolved here
                if item.name not in label_dependent_consts:
                    unresolved.append(item.name)
        if unresolved:
            raise CompilerPanic(f"Circular dependency detected in constants: {unresolved}")

    return label_dependent_consts


def _resolve_label_dependent_constants(
    assembly: list[AssemblyInstruction],
    symbol_map: dict[SymbolKey, int],
    label_dependent_consts: set[str],
):
    """
    Resolve constants that depend on labels, now that labels have been positioned.
    Validates that values fit within 16-bit PUSH2 limit.
    """
    max_push2_value = 0xFFFF  # 65535 - maximum value for PUSH2

    # Try to resolve remaining constants
    max_iterations = 100
    iterations = 0

    while iterations < max_iterations:
        changed = False
        for item in assembly:
            if isinstance(item, BaseConstOp):
                const_ref = CONSTREF(item.name)
                # Skip if already resolved
                if const_ref in symbol_map:
                    continue

                # Try to calculate the value
                if (value := item.calculate(symbol_map)) is not None:
                    # Check overflow for label-dependent constants
                    if item.name in label_dependent_consts and value > max_push2_value:
                        raise CompilerPanic(
                            f"Label-dependent constant '{item.name}' has value {value} "
                            "(constants involving labels must fit in PUSH2 instructions)"
                        )
                    _add_to_symbol_map(symbol_map, const_ref, value)
                    changed = True

        if not changed:
            break

        iterations += 1

    # Check for unresolved constants
    unresolved = []
    for item in assembly:
        if isinstance(item, BaseConstOp) and CONSTREF(item.name) not in symbol_map:
            unresolved.append(item.name)
    if unresolved:
        raise CompilerPanic(f"Could not resolve label-dependent constants: {unresolved}")


def resolve_symbols(
    assembly: list[AssemblyInstruction],
) -> tuple[dict[SymbolKey, int], dict[str, Any]]:
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

    symbol_map: dict[SymbolKey, int] = {}

    pc: int = 0

    # First pass: resolve constants that don't depend on labels
    # and identify which constants depend on labels
    label_dependent_consts = _resolve_constants(assembly, symbol_map)

    # resolve labels (i.e. JUMPDEST locations) to actual code locations,
    # and simultaneously build the source map.
    for i, item in enumerate(assembly):
        # add it to the source map
        note_line_num(source_map, pc, item)

        # update pc_jump_map
        if item == "JUMP":
            last = assembly[i - 1]
            if (
                isinstance(last, PUSHLABEL) or isinstance(last, PUSHLABELJUMPDEST)
            ) and last.label.label.startswith("internal"):
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

        if isinstance(item, BaseConstOp):
            continue  # CONST operations do not go into bytecode

        # update pc
        if isinstance(item, JUMPDEST):
            _add_to_symbol_map(symbol_map, item.label, pc)
            pc += 1  # jumpdest

        elif isinstance(item, Label):
            _add_to_symbol_map(symbol_map, item, pc)

        elif isinstance(item, (PUSHLABEL, PUSHLABELJUMPDEST)):
            pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits

        elif isinstance(item, PUSH_OFST):
            assert isinstance(item.ofst, int), item
            # [PUSH_OFST, (Label foo), bar] -> PUSH2 (foo+bar)
            # [PUSH_OFST, _mem_foo, bar] -> PUSHN (foo+bar)
            if isinstance(item.label, Label):
                pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
            elif isinstance(item.label, CONSTREF):
                # Check if this constant depends on labels
                const_name = item.label.label
                if const_name in label_dependent_consts:
                    # Use fixed PUSH2 size for label-dependent constants
                    pc += SYMBOL_SIZE + 1  # PUSH2 highbits lowbits
                else:
                    # For non-label-dependent constants, calculate actual size
                    # Try to look up as a CONSTREF first
                    if item.label in symbol_map:
                        const = symbol_map[item.label]
                        val = const + item.ofst
                        pc += calc_push_size(val)
                    else:
                        # Treat it as a label-dependent reference using PUSH2 size
                        pc += SYMBOL_SIZE + 1  # PUSH2
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

    # Second pass: now that labels are positioned, resolve label-dependent constants
    _resolve_label_dependent_constants(assembly, symbol_map, label_dependent_consts)

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
    segments = []
    current_segment_length = 0

    for item in assembly:
        if isinstance(item, Label):
            if current_segment_length > 0:
                segments.append(current_segment_length)
                current_segment_length = 0
            continue

        if not isinstance(item, DATA_ITEM):
            # Only DATA_ITEM contributes to segment length
            continue

        # Add to current segment length
        if is_symbol(item.data):
            current_segment_length += SYMBOL_SIZE
        elif isinstance(item.data, bytes):
            current_segment_length += len(item.data)
        else:  # pragma: nocover
            raise ValueError(f"invalid data {type(item)} {item}")

    # Add the final segment if it has data
    if current_segment_length > 0:
        segments.append(current_segment_length)

    return segments


def _compile_data_item(item: DATA_ITEM, symbol_map: dict[SymbolKey, int]) -> bytes:
    if isinstance(item.data, bytes):
        return item.data
    if isinstance(item.data, Label):
        if item.data not in symbol_map:
            raise CompilerPanic(f"Unresolved label in data section: {item.data}")
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


def _validate_assembly_jumps(assembly: list[AssemblyInstruction], symbol_map: dict[SymbolKey, int]):
    """
    Validate assembly jumpdest and jump references for correctness before generating bytecode
    """
    # Track all jump destinations and references
    jump_dests = set()
    jump_refs = set()

    for item in assembly:
        if isinstance(item, JUMPDEST):
            jump_dests.add(item.label)
        elif isinstance(item, PUSHLABELJUMPDEST):
            jump_refs.add(item.label)

    # Check all jump references have destinations
    missing_dests = jump_refs - jump_dests
    if missing_dests:
        missing_labels = [
            label.label if hasattr(label, "label") else str(label) for label in missing_dests
        ]
        raise CompilerPanic(f"Jump references without destinations: {missing_labels}")


def assembly_to_evm(assembly: list[AssemblyInstruction]) -> tuple[bytes, dict[str, Any]]:
    """
    Generate bytecode and source map from assembly

    Returns:
        bytecode: bytestring of the EVM bytecode
        source_map: source map dict that gets output for the user
    """
    # This API might seem a bit strange, but it's backwards compatible
    symbol_map, source_map = resolve_symbols(assembly)
    _validate_assembly_jumps(assembly, symbol_map)

    # Extract label-dependent constants from the assembly for bytecode generation
    label_dependent_consts = set()
    for item in assembly:
        if isinstance(item, BaseConstOp):
            # Check if this constant references labels
            for operand in [item.op1, item.op2]:
                if isinstance(operand, str) and Label(operand) in symbol_map:
                    label_dependent_consts.add(item.name)

    # Propagate label dependency
    changed = True
    while changed:
        changed = False
        for item in assembly:
            if isinstance(item, BaseConstOp) and item.name not in label_dependent_consts:
                for operand in [item.op1, item.op2]:
                    if isinstance(operand, str) and operand in label_dependent_consts:
                        label_dependent_consts.add(item.name)
                        changed = True

    bytecode = _assembly_to_evm(assembly, symbol_map, label_dependent_consts)
    return bytecode, source_map


def _assembly_to_evm(
    assembly: list[AssemblyInstruction],
    symbol_map: dict[SymbolKey, int],
    label_dependent_consts: set[str],
) -> bytes:
    """
    Assembles assembly into EVM bytecode

    Parameters:
        assembly: list of asm instructions
        symbol_map: dict from labels to resolved locations in the code
        label_dependent_consts: set of constant names that depend on labels

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
        elif isinstance(item, BaseConstOp):
            continue  # CONST operations do not show up in bytecode
        elif isinstance(item, Label):
            continue  # Label does not show up in bytecode

        elif isinstance(item, (PUSHLABEL, PUSHLABELJUMPDEST)):
            # push a symbol to stack
            label = item.label
            bytecode = _compile_push_instruction(PUSH_N(symbol_map[label], n=SYMBOL_SIZE))
            ret.extend(bytecode)

        elif isinstance(item, JUMPDEST):
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
                const_name = item.label.label

                # Try to look up as a CONSTREF first
                if item.label in symbol_map:
                    ofst = symbol_map[item.label] + item.ofst
                # If not found as CONSTREF, try as a Label
                elif Label(const_name) in symbol_map:
                    ofst = symbol_map[Label(const_name)] + item.ofst
                else:
                    raise CompilerPanic(f"Unknown symbol: {const_name}")

                # Check if this is a label-dependent constant
                if const_name in label_dependent_consts:
                    # Use PUSH2 for label-dependent constants
                    # Also validate the value fits in 16 bits
                    if ofst > 0xFFFF:
                        raise CompilerPanic(
                            f"PUSH_OFST with label-dependent constant '{const_name}' "
                            f"has value {ofst} which exceeds 16-bit limit"
                        )
                    bytecode = _compile_push_instruction(PUSH_N(ofst, SYMBOL_SIZE))
                else:
                    # Use optimal size for non-label-dependent constants
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
