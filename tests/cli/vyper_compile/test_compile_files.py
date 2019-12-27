import pytest

from vyper.cli.vyper_compile import (
    compile_files,
)


def test_combined_json_keys(tmp_path):
    bar_path = tmp_path.joinpath('bar.vy')
    with bar_path.open('w') as fp:
        fp.write("")

    combined_keys = {'bytecode', 'bytecode_runtime', 'abi', 'source_map', 'method_identifiers'}
    compile_data = compile_files([bar_path], ['combined_json'], root_folder=tmp_path)

    assert set(compile_data.keys()) == {'bar.vy', 'version'}
    assert set(compile_data['bar.vy'].keys()) == combined_keys


def test_invalid_root_path():
    with pytest.raises(FileNotFoundError):
        compile_files([], [], root_folder="path/that/does/not/exist")


def test_evm_versions(tmp_path):
    # should compile differently because of SELFBALANCE
    code = """
@public
def foo() -> uint256(wei):
    return self.balance
"""

    bar_path = tmp_path.joinpath('bar.vy')
    with bar_path.open('w') as fp:
        fp.write(code)

    compile_data = compile_files(
        [bar_path],
        output_formats=['bytecode_runtime'],
        evm_version="byzantium"
    )
    assert compile_data != compile_files(
        [bar_path],
        output_formats=['bytecode_runtime'],
        evm_version="istanbul"
    )
