import itertools

import pytest

from vyper import (
    __version__,
)


@pytest.fixture
def make_tmp_vy_file(tmp_path):
    name_count = itertools.count()

    def _make(src):
        name = f'tmp{next(name_count)}.vy'

        src_path = tmp_path / name
        src_path.write_text(src)

        return src_path

    return _make


@pytest.fixture
def tmp_vy_file_1(make_tmp_vy_file):
    return make_tmp_vy_file("""
@public
def a() -> bool:
    return True
    """)


@pytest.fixture
def tmp_vy_file_2(make_tmp_vy_file):
    return make_tmp_vy_file("""
@public
def meaning_of_life() -> uint256:
    return 42
    """)


@pytest.mark.script_launch_mode('subprocess')
def test_version(script_runner):
    ret = script_runner.run('vyper', '--version')

    assert ret.stdout == __version__ + '\n'


@pytest.mark.script_launch_mode('subprocess')
def test_compile_one_file(script_runner, tmp_vy_file_1):
    ret = script_runner.run('vyper', '-f', 'bytecode', tmp_vy_file_1)

    assert ret.stdout == '0x6100c256600035601c52740100000000000000000000000000000000000000006020526f7fffffffffffffffffffffffffffffff6040527fffffffffffffffffffffffffffffffff8000000000000000000000000000000060605274012a05f1fffffffffffffffffffffffffdabf41c006080527ffffffffffffffffffffffffed5fa0e000000000000000000000000000000000060a052630dbe671f60005114156100b85734156100ac57600080fd5b600160005260206000f3005b60006000fd5b6100046100c2036100046000396100046100c2036000f3\n'  # noqa: E501


@pytest.mark.script_launch_mode('subprocess')
def test_compile_two_files(script_runner, tmp_vy_file_1, tmp_vy_file_2):
    ret = script_runner.run('vyper', '-f', 'bytecode', tmp_vy_file_1, tmp_vy_file_2)

    assert ret.stdout == '0x6100c256600035601c52740100000000000000000000000000000000000000006020526f7fffffffffffffffffffffffffffffff6040527fffffffffffffffffffffffffffffffff8000000000000000000000000000000060605274012a05f1fffffffffffffffffffffffffdabf41c006080527ffffffffffffffffffffffffed5fa0e000000000000000000000000000000000060a052630dbe671f60005114156100b85734156100ac57600080fd5b600160005260206000f3005b60006000fd5b6100046100c2036100046000396100046100c2036000f3\n0x6100c256600035601c52740100000000000000000000000000000000000000006020526f7fffffffffffffffffffffffffffffff6040527fffffffffffffffffffffffffffffffff8000000000000000000000000000000060605274012a05f1fffffffffffffffffffffffffdabf41c006080527ffffffffffffffffffffffffed5fa0e000000000000000000000000000000000060a052634f452d6060005114156100b85734156100ac57600080fd5b602a60005260206000f3005b60006000fd5b6100046100c2036100046000396100046100c2036000f3\n'  # noqa: E501
