#!/usr/bin/env python3
import sys
import argparse

MAGIC = b'\xEF\x00'
VERSION = 0x01
S_TERMINATOR = 0x00
S_TYPE = 0x01
S_CODE = 0x02
S_DATA = 0x03

class ValidationException(Exception):
    """Validation exception."""

class FunctionType:
  def __init__(self, inputs, outputs) -> None:
      self.inputs = inputs
      self.outputs = outputs

# The ranges below are as specified in the Yellow Paper.
# Note: range(s, e) excludes e, hence the +1
valid_opcodes = [
    *range(0x00, 0x0b + 1),
    *range(0x10, 0x1d + 1),
    0x20,
    *range(0x30, 0x3f + 1),
    *range(0x40, 0x48 + 1),
    *range(0x50, 0x55 + 1), *range(0x58, 0x5d + 1),
    *range(0x60, 0x6f + 1),
    *range(0x70, 0x7f + 1),
    *range(0x80, 0x8f + 1),
    *range(0x90, 0x9f + 1),
    *range(0xa0, 0xa4 + 1),
    0xb0, 0xb1, 0xb2,
    # Note: 0xfe is considered assigned.
    0xf0, 0xf1, 0xf3, 0xf4, 0xf5, 0xfa, 0xfd, 0xfe
]

# STOP, RETF, JUMPF, RETURN, REVERT, INVALID
terminating_opcodes = [0x00, 0xb1, 0xb2, 0xf3, 0xfd, 0xfe]

immediate_sizes = 256 * [0]
immediate_sizes[0x5c] = 2  # RJUMP
immediate_sizes[0x5d] = 2  # RJUMPI
immediate_sizes[0xb0] = 2  # CALLF
immediate_sizes[0xb2] = 2  # JUMPF
for opcode in range(0x60, 0x7f + 1):  # PUSH1..PUSH32
    immediate_sizes[opcode] = opcode - 0x60 + 1

# Validate EOF code.
# Raises ValidationException on invalid code
def validate_eof(code: bytes):
    # Check version
    if len(code) < 3 or code[2] != VERSION:
        raise ValidationException("invalid version")

    # Process section headers
    section_sizes = {S_TYPE: [], S_CODE: [], S_DATA: []}
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
          section_sizes[S_CODE] = [0] * section_count
          pos += section_count * 2
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

    # The entire container must be scanned
    # print(section_sizes, (pos + sum(section_sizes[S_TYPE]) + sum(section_sizes[S_CODE]) + sum(section_sizes[S_DATA])))
    # if len(code) != (pos + sum(section_sizes[S_TYPE]) + sum(section_sizes[S_CODE]) + sum(section_sizes[S_DATA])):
    #     raise ValidationException("container size not equal to sum of section sizes")

    # First type section, if present, has 0 inputs and 0 outputs
    if len(section_sizes[S_TYPE]) > 0 and (code[pos] != 0 or code[pos + 1] != 0):
        raise ValidationException("invalid type of section 0")

# Raises ValidationException on invalid code
def validate_code_section(func_id: int, code: bytes, types: list[FunctionType] = [FunctionType(0, 0)]):
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
        if not opcode in valid_opcodes:
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

            if section_id >= len(types):
                raise ValidationException("invalid section id")
        elif opcode == 0xb2:
            if pos + 2 > len(code):
                raise ValidationException("truncated JUMPF immediate")
            section_id = int.from_bytes(code[pos:pos+2], byteorder = "big", signed = False)

            if section_id >= len(types):
                raise ValidationException("invalid section id")

            if types[section_id].outputs != types[func_id].outputs:
                raise ValidationException("incompatible function type for JUMPF")

        # Save immediate value positions
        immediates.update(range(pos, pos + immediate_sizes[opcode]))
        # Skip immediates
        pos += immediate_sizes[opcode]

    # Ensure last opcode's immediate doesn't go over code end
    if pos != len(code):
        raise ValidationException("truncated immediate")

    # opcode is the *last opcode*
    if not opcode in terminating_opcodes:
        raise ValidationException("no terminating instruction")

    # Ensure relative jump destinations don't target immediates
    if not rjumpdests.isdisjoint(immediates):
        raise ValidationException("relative jump destination targets immediate")


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Vyper EOFv1 validation utility",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "input_file",
        help="Input file containing the EOFv1 formated bytecode",
        nargs="?",
    )

    args = parser.parse_args(argv)

    if args.input_file:
      with open(args.input_file, "r") as f:
        code = bytes.fromhex(f.read())
        validate_eof(code)

if __name__ == "__main__":
    _parse_args(sys.argv[1:])