from vyper.exceptions import VyperInternalException

MAGIC = b'\xEF\x00'
VERSION = 0x01
S_TERMINATOR = 0x00
S_TYPE = 0x01
S_CODE = 0x02
S_DATA = 0x03

class ValidationException(VyperInternalException):
    """Validation exception."""

class EOFReader:
    bytecode: bytes

    def __init__(self, bytecode: bytes):
        self.bytecode = bytecode
        self._verify_header()

    def get_code_segments(self):
        pass

    def _verify_header(self) -> bool:
        if self.bytecode[:2] != MAGIC or self.bytecode[2] != VERSION:
            raise ValidationException(f"not an EOFv{VERSION} bytecode")

        code = self.bytecode

        # Process section headers
        section_sizes = {S_TYPE: [], S_CODE: [], S_DATA: []}
        code_section_ios = []
        code_sections = []
        data_sections = []
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