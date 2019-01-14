from vyper.compiler import (
    compile_codes,
    compile_code
)


def test_basic_extract_interface():
    code = """
# Functions

@constant
@public
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    out = compile_code(code, ['interface'])
    out = out['interface']
    code_pass = '\n'.join(code.split('\n')[:-2] + ['    pass'])  # replace with a pass statement.

    assert code_pass.strip() == out.strip()


def test_basic_extract_external_interface():
    code = """
@constant
@public
def allowance(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2

@public
def test(_owner: address):
    pass

@constant
@private
def _prive(_owner: address, _spender: address) -> (uint256, uint256):
    return 1, 2
    """

    interface = """
# External Contracts
contract One:
    def allowance(_owner: address, _spender: address) -> (uint256, uint256): constant
    def test(_owner: address): modifying
    """

    out = compile_codes({'one.vy': code}, ['external_interface'])[0]
    out = out['external_interface']

    assert interface.strip() == out.strip()
