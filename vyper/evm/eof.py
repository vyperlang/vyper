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
        self._verifyHeader()

    def _verifyHeader(self) -> bool:
        if self.bytecode[:2] != MAGIC or self.bytecode[2] != VERSION:
            raise ValidationException(f"not an EOFv{VERSION} bytecode")