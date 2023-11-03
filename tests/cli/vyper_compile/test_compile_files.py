import pytest

from pathlib import Path

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
    compile_data = compile_files(["bar.vy"], ["combined_json"], root_folder=tmp_path)

    assert set(compile_data.keys()) == {Path("bar.vy"), "version"}
    assert set(compile_data[Path("bar.vy")].keys()) == combined_keys


def test_invalid_root_path():
    with pytest.raises(FileNotFoundError):
        compile_files([], [], root_folder="path/that/does/not/exist")
