from vyper.exceptions import VyperInternalException
from vyper.evm.opcodes import TERMINATING_OPCODES, VALID_OPCODES, immediate_size, get_mnemonic

MAGIC = b'\xEF\x00'
VERSION = 0x01
S_TERMINATOR = 0x00
S_TYPE = 0x01
S_CODE = 0x02
S_DATA = 0x03

class ValidationException(VyperInternalException):
    """Validation exception."""

class FunctionType:
    def __init__(self, inputs, outputs, max_stack_height) -> None:
        self.offset = 0
        self.code = bytes()
        self.inputs = inputs
        self.outputs = outputs
        self.max_stack_height = max_stack_height

class EOFReader:
    bytecode: bytes

    def __init__(self, bytecode: bytes):
        self.bytecode = bytecode
        self.code_sections = []
        self.data_sections = []
        self._verify_header()

    def get_code_segments(self):
        pass

    def _verify_header(self) -> bool:
        if self.bytecode[:2] != MAGIC or self.bytecode[2] != VERSION:
            raise ValidationException(f"not an EOFv{VERSION} bytecode")

        code = self.bytecode

        # Process section headers
        section_sizes = {S_TYPE: [], S_CODE: [], S_DATA: []}
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
            if not section_id in section_sizes:
                raise ValidationException("invalid section id")

            # Data section preceding code section (i.e. code section following data section)
            if section_id == S_CODE and len(section_sizes[S_DATA]) != 0:
                raise ValidationException("data section preceding code section")

            # Code section or data section preceding type section
            if section_id == S_TYPE and (len(section_sizes[S_CODE]) != 0 or len(section_sizes[S_DATA]) != 0):
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
                for i in range(section_count):
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
        if section_sizes[S_TYPE][0] != 0 and section_sizes[S_TYPE][0] != len(section_sizes[S_CODE]) * 4:
            raise ValidationException("invalid type section size")

        # Truncated section size
        if (pos + len(section_sizes[S_CODE]) * 4) > len(code):
            raise ValidationException("truncated TYPE section size")

        # Read TYPE section
        for i in range(len(section_sizes[S_CODE])):
            input_count = code[pos]
            output_count = code[pos + 1]
            max_stack_height = (code[pos + 2] << 8) | code[pos + 3]
            type = FunctionType(input_count, output_count, max_stack_height)
            self.code_sections.append(type)
            pos += 4

        # Read CODE sections
        for i, section_size in enumerate(section_sizes[S_CODE]):
            # Truncated section size
            if (pos + section_size) > len(code):
                raise ValidationException("truncated CODE section size")
            self.code_sections[i].code = code[pos:pos + section_size]
            self.code_sections[i].offset = pos
            pos += section_size

            self.validate_code_section(i)

        # Read DATA sections
        for section_size in section_sizes[S_DATA]:
            # Truncated section size
            if (pos + section_size) > len(code):
                raise ValidationException("truncated DATA section size")
            self.data_sections.append(code[pos:pos + section_size])
            pos += section_size

        if (pos) != len(code):
            raise ValidationException("Bad file size")

        # First code section should have zero inputs and outputs
        if self.code_sections[0].inputs != 0 or self.code_sections[0].outputs != 0:
            raise ValidationException("invalid input/output count for code section 0")


    # Raises ValidationException on invalid code
    def validate_code_section(self, func_id: int):
        code = self.code_sections[func_id].code

        # Note that EOF1 already asserts this with the code section requirements
        assert len(code) > 0

        opcode = 0
        pos = 0
        rjumpdests = set()
        immediates = set()
        while pos < len(code):
            # Ensure the opcode is valid
            opcode = code[pos]
            pos += 1
            if not opcode in VALID_OPCODES:
                raise ValidationException("undefined instruction")

            if opcode == 0x5c or opcode == 0x5d:
                if pos + 2 > len(code):
                    raise ValidationException("truncated relative jump offset")
                offset = int.from_bytes(code[pos:pos+2], byteorder = "big", signed = True)

                rjumpdest = pos + 2 + offset
                if rjumpdest < 0 or rjumpdest >= len(code):
                    raise ValidationException("relative jump destination out of bounds")

                rjumpdests.add(rjumpdest)
            elif opcode == 0xb0:
                if pos + 2 > len(code):
                    raise ValidationException("truncated CALLF immediate")
                section_id = int.from_bytes(code[pos:pos+2], byteorder = "big", signed = False)

                if section_id >= len(self.code_sections):
                    raise ValidationException("invalid section id")
            elif opcode == 0xb2:
                if pos + 2 > len(code):
                    raise ValidationException("truncated JUMPF immediate")
                section_id = int.from_bytes(code[pos:pos+2], byteorder = "big", signed = False)

                if section_id >= len(self.code_sections):
                    raise ValidationException("invalid section id")

                if self.code_sections[section_id].outputs != self.code_sections[func_id].outputs:
                    raise ValidationException("incompatible function type for JUMPF")

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
