import pytest

@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, 'utf-8') + bytearray(length-len(str))
    return bytes_helper
