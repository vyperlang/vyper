from collections import deque

from vyper.evm.opcodes import (
    TERMINATING_OPCODES,
    VALID_OPCODES,
    get_mnemonic,
    get_opcode_metadata,
    immediate_size,
)
from vyper.exceptions import VyperInternalException
from vyper.utils import OrderedSet

MAGIC = b"\xEF\x00"
VERSION = 0x01
S_TERMINATOR = 0x00
S_TYPE = 0x01
S_CODE = 0x02
S_DATA = 0x03


class ValidationException(VyperInternalException):
    """Validation exception."""


class FunctionType:
    def __init__(self, function_id, inputs, outputs, max_stack_height) -> None:
        self.function_id = function_id
        self.offset = 0
        self.code = bytes()
        self.inputs = inputs
        self.outputs = outputs
        self.max_stack_height = max_stack_height

    def disassemble(self):
        output = (
            f"Func {self.function_id}:\nCode segment offset:{self.offset}"
            f" inputs:{self.inputs} outputs:{self.outputs}"
            f" max stack height:{self.max_stack_height}\n"
        )
        code = deque(self.code)
        while code:
            pc = len(self.code) - len(code)
            op = code.popleft()
            mnemonic = get_mnemonic(op)
            immediates_len = immediate_size(mnemonic)
            immediates = "0x" + "".join([f"{code.popleft():02x}" for _ in range(immediates_len)])
            output += f"{pc:04x}: {mnemonic}"
            if immediates_len > 0:
                output += f" {immediates}"
            output += "\n"

        return output + "\n"


class EOFReader:
    bytecode: bytes

    code_sections: list[FunctionType]
    data_sections: list[bytes]

    def __init__(self, bytecode: bytes):
        self.bytecode = bytecode
        self.bytecode_size = 0
        self.code_sections = []
        self.data_sections = []
        self._verify_header()

    def get_code_segments(self):
        pass

    def _verify_header(self) -> None:
        if self.bytecode[:2] != MAGIC or self.bytecode[2] != VERSION:
            raise ValidationException(f"not an EOFv{VERSION} bytecode")

        code = self.bytecode

        # Process section headers
        section_sizes: dict[int, list[int]] = {S_TYPE: [], S_CODE: [], S_DATA: []}
        self.code_sections = []
        self.data_sections = []
        pos = 3
        while True:
            # Terminator not found
            if pos >= len(code):
                raise ValidationException("no section terminator")

            section_id = code[pos]
            pos += 1
            if section_id == S_TERMINATOR:
                break

            # Disallow unknown sections
            if section_id not in section_sizes:
                raise ValidationException("invalid section id")

            # Data section preceding code section (i.e. code section following data section)
            if section_id == S_CODE and len(section_sizes[S_DATA]) != 0:
                raise ValidationException("data section preceding code section")

            # Code section or data section preceding type section
            if section_id == S_TYPE and (
                len(section_sizes[S_CODE]) != 0 or len(section_sizes[S_DATA]) != 0
            ):
                raise ValidationException("code or data section preceding type section")

            # Multiple type or data sections
            if section_id == S_TYPE and len(section_sizes[S_TYPE]) != 0:
                raise ValidationException("multiple type sections")
            if section_id == S_DATA and len(section_sizes[S_DATA]) != 0:
                raise ValidationException("multiple data sections")

            # Truncated section size
            if (pos + 1) >= len(code):
                raise ValidationException("truncated section size")

            section_count = (code[pos] << 8) | code[pos + 1]
            pos += 2
            if section_id == S_TYPE:
                section_sizes[S_TYPE].append(section_count)
            elif section_id == S_CODE:
                for _i in range(section_count):
                    code_size = (code[pos] << 8) | code[pos + 1]
                    pos += 2
                    section_sizes[S_CODE].append(code_size)
            elif section_id == S_DATA:
                section_sizes[S_DATA].append(section_count)

        # Code section cannot be absent
        if len(section_sizes[S_CODE]) == 0:
            raise ValidationException("no code section")

        # Not more than 1024 code sections
        if len(section_sizes[S_CODE]) > 1024:
            raise ValidationException("more than 1024 code sections")

        # Type section can be absent only if single code section is present
        if len(section_sizes[S_TYPE]) == 0 and len(section_sizes[S_CODE]) != 1:
            raise ValidationException("no obligatory type section")

        # Type section, if present, has size corresponding to number of code sections
        if (
            section_sizes[S_TYPE][0] != 0
            and section_sizes[S_TYPE][0] != len(section_sizes[S_CODE]) * 4
        ):
            raise ValidationException("invalid type section size")

        # Truncated section size
        if (pos + len(section_sizes[S_CODE]) * 4) > len(code):
            raise ValidationException("truncated TYPE section size")

        # Read TYPE section
        for i in range(len(section_sizes[S_CODE])):
            input_count = code[pos]
            output_count = code[pos + 1]
            max_stack_height = (code[pos + 2] << 8) | code[pos + 3]
            type = FunctionType(i, input_count, output_count, max_stack_height)
            self.code_sections.append(type)
            pos += 4

        # Read CODE sections
        for i, section_size in enumerate(section_sizes[S_CODE]):
            # Truncated section size
            if (pos + section_size) > len(code):
                raise ValidationException("truncated CODE section size")
            self.code_sections[i].code = code[pos : pos + section_size]
            self.code_sections[i].offset = pos
            pos += section_size

            self.validate_code_section(i)

        # Read DATA sections
        for section_size in section_sizes[S_DATA]:
            # Truncated section size
            if (pos + section_size) > len(code):
                raise ValidationException("truncated DATA section size")
            self.data_sections.append(code[pos : pos + section_size])
            pos += section_size

        # Check if we have a second EOF header attached (the runtime container)
        if (pos) != len(code) and (
            self.bytecode[pos : pos + 2] != MAGIC or self.bytecode[pos + 2] != VERSION
        ):
            raise ValidationException("Bad file size")

        # First code section should have zero inputs and outputs
        if self.code_sections[0].inputs != 0 or self.code_sections[0].outputs != 0:
            raise ValidationException("invalid input/output count for code section 0")

        self.bytecode_size = pos

    # Raises ValidationException on invalid code
    def validate_code_section(self, func_id: int):
        code = self.code_sections[func_id].code

        # Note that EOF1 already asserts this with the code section requirements
        assert len(code) > 0

        opcode = 0
        pos = 0
        rjumpdests = set[int]()
        immediates = OrderedSet[int]()
        while pos < len(code):
            # Ensure the opcode is valid
            opcode = code[pos]
            pos += 1
            if opcode not in VALID_OPCODES:
                raise ValidationException("undefined instruction")

            if opcode == 0x5C or opcode == 0x5D:
                if pos + 2 > len(code):
                    raise ValidationException("truncated relative jump offset")
                offset = int.from_bytes(code[pos : pos + 2], byteorder="big", signed=True)

                rjumpdest = pos + 2 + offset
                if rjumpdest < 0 or rjumpdest >= len(code):
                    raise ValidationException("relative jump destination out of bounds")

                rjumpdests.add(rjumpdest)
            elif opcode == 0xB0:
                if pos + 2 > len(code):
                    raise ValidationException("truncated CALLF immediate")
                section_id = int.from_bytes(code[pos : pos + 2], byteorder="big", signed=False)

                if section_id >= len(self.code_sections):
                    raise ValidationException("invalid section id")

            # Save immediate value positions
            immediates.update(range(pos, pos + immediate_size(opcode)))
            # Skip immediates
            pos += immediate_size(opcode)

        # Ensure last opcode's immediate doesn't go over code end
        if pos != len(code):
            raise ValidationException("truncated immediate")

        # opcode is the *last opcode*
        if not get_mnemonic(opcode) in TERMINATING_OPCODES:
            raise ValidationException("no terminating instruction")

        # Ensure relative jump destinations don't target immediates
        if not rjumpdests.isdisjoint(immediates):
            raise ValidationException("relative jump destination targets immediate")

    def disassemble(self):
        output = ""
        for code in self.code_sections:
            output += code.disassemble()

        return output


# Calculates the max stack height for the given code block. Meanwhile calculates
# the stack height at every instruction to be later used to validate jump
# destination stack validity. Currently disabled.
def calculate_max_stack_height(
    bytecode: bytes, start_pc: int = 0, stack_height: int = 0, stack_heights=None
) -> int:
    if stack_heights is None:
        stack_heights = []

    max_stack_height = 0

    if len(stack_heights) == 0:
        stack_heights = [-1] * len(bytecode)

    pc = start_pc
    while pc < len(bytecode):
        op = bytecode[pc]
        meta = get_opcode_metadata(op)
        mnemonic = get_mnemonic(meta[0])
        pop_size = meta[1]
        push_size = meta[2]

        if mnemonic == "CALLF":
            pop_size = 0
            push_size = 1

        stack_height -= pop_size
        if stack_height < 0:
            raise ValidationException("Stack underflow")
        stack_height += push_size
        max_stack_height = max(max_stack_height, stack_height)

        # fill the stack height buffer
        stack_heights[pc : pc + immediate_size(op) + 1] = [stack_height] * (immediate_size(op) + 1)
        # print(pc, mnemonic, stack_heights, max_stack_height)

        if mnemonic == "RJUMP":
            jump_offset = int.from_bytes(bytecode[pc + 1 : pc + 3], byteorder="big", signed=True)
            # if     stack_heights[pc+jump_offset] != -1
            #    and stack_heights[pc+jump_offset] != stack_height:
            #     raise ValidationException("Stack height missmatch at jump target")
            if stack_heights[pc + jump_offset] != -1:
                return max_stack_height
            pc += jump_offset
        elif mnemonic == "RJUMPI":
            jump_offset = int.from_bytes(bytecode[pc + 1 : pc + 3], byteorder="big", signed=True)
            return max(
                max_stack_height,
                calculate_max_stack_height(bytecode, pc + 3, stack_height, stack_heights),
                calculate_max_stack_height(
                    bytecode, pc + 3 + jump_offset, stack_height, stack_heights
                ),
            )
        elif mnemonic in TERMINATING_OPCODES:
            return max_stack_height

        pc += 1 + immediate_size(op)

    return max_stack_height
