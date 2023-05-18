import pytest

from vyper.cli.vyper_compile import compile_files


def test_combined_json_keys(tmp_path):
    bar_path = tmp_path.joinpath("bar.vy")
    with bar_path.open("w") as fp:
        fp.write("")

    combined_keys = {
        "bytecode",
        "bytecode_runtime",
        "blueprint_bytecode",
        "abi",
        "source_map",
        "layout",
        "method_identifiers",
        "userdoc",
        "devdoc",
    }
    compile_data = compile_files([bar_path], ["combined_json"], root_folder=tmp_path)

    assert set(compile_data.keys()) == {"bar.vy", "version"}
    assert set(compile_data["bar.vy"].keys()) == combined_keys


def test_invalid_root_path():
    with pytest.raises(FileNotFoundError):
        compile_files([], [], root_folder="path/that/does/not/exist")


def test_evm_versions(tmp_path):
    # should compile differently because of SELFBALANCE
    code = """
@external
def foo() -> uint256:
    return self.balance
"""

    bar_path = tmp_path.joinpath("bar.vy")
    with bar_path.open("w") as fp:
        fp.write(code)

    byzantium_bytecode = compile_files(
        [bar_path], output_formats=["bytecode"], evm_version="byzantium"
    )[str(bar_path)]["bytecode"]
    istanbul_bytecode = compile_files(
        [bar_path], output_formats=["bytecode"], evm_version="istanbul"
    )[str(bar_path)]["bytecode"]

    assert byzantium_bytecode != istanbul_bytecode

    # SELFBALANCE opcode is 0x47
    assert "47" not in byzantium_bytecode
    assert "47" in istanbul_bytecode
