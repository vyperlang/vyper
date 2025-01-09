import contextlib
import json
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

from vyper.cli.compile_archive import compiler_data_from_zip
from vyper.cli.vyper_compile import compile_files
from vyper.cli.vyper_json import compile_from_input_dict, compile_json
from vyper.compiler import INTERFACE_OUTPUT_FORMATS, OUTPUT_FORMATS
from vyper.compiler.input_bundle import FilesystemInputBundle
from vyper.compiler.output_bundle import OutputBundle
from vyper.compiler.phases import CompilerData
from vyper.utils import sha256sum

TAMPERED_INTEGRITY_SUM = sha256sum("tampered integrity sum")

INTEGRITY_WARNING = f"Mismatched integrity sum! Expected {TAMPERED_INTEGRITY_SUM}"
INTEGRITY_WARNING += " but got {integrity}."  # noqa: FS003
INTEGRITY_WARNING += " (This likely indicates a corrupted archive)"


def test_combined_json_keys(chdir_tmp_path, make_file):
    make_file("bar.vy", "")

    combined_keys = {
        "bytecode",
        "bytecode_runtime",
        "blueprint_bytecode",
        "abi",
        "source_map",
        "source_map_runtime",
        "layout",
        "method_identifiers",
        "userdoc",
        "devdoc",
    }
    compile_data = compile_files(["bar.vy"], ["combined_json"])

    assert set(compile_data.keys()) == {Path("bar.vy"), "version"}
    assert set(compile_data[Path("bar.vy")].keys()) == combined_keys


def test_invalid_root_path():
    with pytest.raises(FileNotFoundError):
        compile_files([], [], paths=["path/that/does/not/exist"])


CONTRACT_CODE = """
{import_stmt}

@external
def foo() -> {alias}.FooStruct:
    return {alias}.FooStruct(foo_=13)

@external
def bar(a: address) -> {alias}.FooStruct:
    return extcall {alias}(a).bar()
"""

INTERFACE_CODE = """
struct FooStruct:
    foo_: uint256

@external
def foo() -> FooStruct:
    ...

@external
def bar() -> FooStruct:
    ...
"""


SAME_FOLDER_IMPORT_STMT = [
    ("import IFoo as IFoo", "IFoo"),
    ("import contracts.IFoo as IFoo", "IFoo"),
    ("from . import IFoo", "IFoo"),
    ("from contracts import IFoo", "IFoo"),
    ("from ..contracts import IFoo", "IFoo"),
    ("from . import IFoo as FooBar", "FooBar"),
    ("from contracts import IFoo as FooBar", "FooBar"),
    ("from ..contracts import IFoo as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt,alias", SAME_FOLDER_IMPORT_STMT)
def test_import_same_folder(import_stmt, alias, chdir_tmp_path, make_file):
    foo = "contracts/foo.vy"
    make_file("contracts/foo.vy", CONTRACT_CODE.format(import_stmt=import_stmt, alias=alias))
    make_file("contracts/IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"]) is not None


SUBFOLDER_IMPORT_STMT = [
    ("import other.IFoo as IFoo", "IFoo"),
    ("import contracts.other.IFoo as IFoo", "IFoo"),
    ("from other import IFoo", "IFoo"),
    ("from contracts.other import IFoo", "IFoo"),
    ("from .other import IFoo", "IFoo"),
    ("from ..contracts.other import IFoo", "IFoo"),
    ("from other import IFoo as FooBar", "FooBar"),
    ("from contracts.other import IFoo as FooBar", "FooBar"),
    ("from .other import IFoo as FooBar", "FooBar"),
    ("from ..contracts.other import IFoo as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt, alias", SUBFOLDER_IMPORT_STMT)
def test_import_subfolder(import_stmt, alias, chdir_tmp_path, make_file):
    foo = make_file(
        "contracts/foo.vy", (CONTRACT_CODE.format(import_stmt=import_stmt, alias=alias))
    )
    make_file("contracts/other/IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"]) is not None


OTHER_FOLDER_IMPORT_STMT = [
    ("import interfaces.IFoo as IFoo", "IFoo"),
    ("from interfaces import IFoo", "IFoo"),
    ("from ..interfaces import IFoo", "IFoo"),
    ("from interfaces import IFoo as FooBar", "FooBar"),
    ("from ..interfaces import IFoo as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt, alias", OTHER_FOLDER_IMPORT_STMT)
def test_import_other_folder(import_stmt, alias, tmp_path, make_file):
    foo = make_file("contracts/foo.vy", CONTRACT_CODE.format(import_stmt=import_stmt, alias=alias))
    make_file("interfaces/IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"], paths=[tmp_path]) is not None


def test_import_parent_folder(tmp_path, make_file):
    foo = make_file(
        "contracts/baz/foo.vy",
        CONTRACT_CODE.format(import_stmt="from ... import IFoo", alias="IFoo"),
    )
    make_file("IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"], paths=[tmp_path]) is not None

    # perform relative import outside of base folder
    compile_files([foo], ["combined_json"], paths=[tmp_path / "contracts"])


def test_import_search_paths(chdir_tmp_path, make_file):
    contract_code = CONTRACT_CODE.format(import_stmt="from utils import IFoo", alias="IFoo")
    contract_filename = "dir1/baz/foo.vy"
    interface_filename = "dir2/utils/IFoo.vyi"
    make_file(interface_filename, INTERFACE_CODE)
    make_file(contract_filename, contract_code)

    assert compile_files([contract_filename], ["combined_json"], paths=["dir2"]) is not None


META_IMPORT_STMT = [
    "import ISelf as ISelf",
    "import contracts.ISelf as ISelf",
    "from . import ISelf",
    "from contracts import ISelf",
]


@pytest.mark.parametrize("import_stmt", META_IMPORT_STMT)
def test_import_self_interface(import_stmt, tmp_path, make_file):
    interface_code = """
struct FooStruct:
    foo_: uint256

@external
def know_thyself(a: address) -> FooStruct:
    ...

@external
def be_known() -> FooStruct:
    ...
    """
    code = f"""
{import_stmt}

@external
def know_thyself(a: address) -> ISelf.FooStruct:
    return extcall ISelf(a).be_known()

@external
def be_known() -> ISelf.FooStruct:
    return ISelf.FooStruct(foo_=42)
    """
    make_file("contracts/ISelf.vyi", interface_code)
    meta = make_file("contracts/Self.vy", code)

    assert compile_files([meta], ["combined_json"], paths=[tmp_path]) is not None


# implement IFoo in another contract for fun
@pytest.mark.parametrize("import_stmt_foo,alias", SAME_FOLDER_IMPORT_STMT)
def test_another_interface_implementation(import_stmt_foo, alias, tmp_path, make_file):
    baz_code = f"""
{import_stmt_foo}

@external
def foo(a: address) -> {alias}.FooStruct:
    return extcall {alias}(a).foo()

@external
def bar(_foo: address) -> {alias}.FooStruct:
    return extcall {alias}(_foo).bar()
    """
    make_file("contracts/IFoo.vyi", INTERFACE_CODE)
    baz = make_file("contracts/Baz.vy", baz_code)

    assert compile_files([baz], ["combined_json"], paths=[tmp_path]) is not None


def test_local_namespace(make_file, chdir_tmp_path):
    # interface code namespaces should be isolated
    # all of these contract should be able to compile together
    codes = [
        "import foo as FooBar",
        "import bar as FooBar",
        "import foo as BarFoo",
        "import bar as BarFoo",
    ]
    struct_def = """
struct FooStruct:
    foo_: uint256

    """

    paths = []
    for i, code in enumerate(codes):
        code += struct_def
        filename = f"code{i}.vy"
        make_file(filename, code)
        paths.append(filename)

    for file_name in ("foo.vyi", "bar.vyi"):
        make_file(file_name, INTERFACE_CODE)

    assert compile_files(paths, ["combined_json"]) is not None


def test_compile_outside_root_path(tmp_path, make_file):
    # absolute paths relative to "."
    make_file("ifoo.vyi", INTERFACE_CODE)
    foo = make_file("foo.vy", CONTRACT_CODE.format(import_stmt="import ifoo as IFoo", alias="IFoo"))

    assert compile_files([foo], ["combined_json"], paths=None) is not None


def test_import_library(tmp_path, make_file):
    library_source = """
@internal
def foo() -> uint256:
    return block.number + 1
    """

    contract_source = """
import lib

@external
def foo() -> uint256:
    return lib.foo()
    """

    make_file("lib.vy", library_source)
    contract_file = make_file("contract.vy", contract_source)

    assert compile_files([contract_file], ["combined_json"], paths=[tmp_path]) is not None


@contextlib.contextmanager
def mock_sys_path(path):
    try:
        sys.path.append(path)
        yield
    finally:
        sys.path.pop()


@pytest.fixture
def input_files(tmp_path_factory, make_file, chdir_tmp_path):
    library_source = """
@internal
def foo() -> uint256:
    return block.number + 1
    """
    json_source = """
[
  {
    "stateMutability": "nonpayable",
    "type": "function",
    "name": "test_json",
    "inputs": [ { "name": "", "type": "uint256" } ],
    "outputs": [ { "name": "", "type": "uint256" } ]
  }
]
    """
    contract_source = """
import lib
import jsonabi

a: uint256
b: uint256

@external
def foo() -> uint256:
    return lib.foo()

@external
def bar(x: uint256) -> uint256:
    return extcall jsonabi(msg.sender).test_json(x)
    """
    storage_layout_overrides = {
        "a": {"type": "uint256", "n_slots": 1, "slot": 5},
        "b": {"type": "uint256", "n_slots": 1, "slot": 0},
    }
    storage_layout_source = json.dumps(storage_layout_overrides)

    tmpdir = tmp_path_factory.mktemp("fake-package")
    with open(tmpdir / "lib.vy", "w") as f:
        f.write(library_source)
    with open(tmpdir / "jsonabi.json", "w") as f:
        f.write(json_source)
    with open(tmpdir / "layout.json", "w") as f:
        f.write(storage_layout_source)

    contract_file = make_file("contract.vy", contract_source)

    contract_hash = sha256sum(contract_source)
    library_hash = sha256sum(library_source)
    jsonabi_hash = sha256sum(json_source)
    resolved_imports_hash = sha256sum(contract_hash + sha256sum(library_hash) + jsonabi_hash)
    storage_layout_hash = sha256sum(storage_layout_source)
    expected_integrity = sha256sum(storage_layout_hash + resolved_imports_hash)

    return (
        tmpdir,
        tmpdir / "lib.vy",
        tmpdir / "jsonabi.json",
        tmpdir / "layout.json",
        contract_file,
        expected_integrity,
    )


def test_import_sys_path(input_files):
    tmpdir, _, _, _, contract_file, _ = input_files
    with mock_sys_path(tmpdir):
        assert compile_files([contract_file], ["combined_json"]) is not None


def test_archive_output(input_files):
    tmpdir, library_file, jsonabi_file, storage_layout_path, contract_file, integrity = input_files
    search_paths = [".", tmpdir]

    s = compile_files(
        [contract_file], ["archive"], paths=search_paths, storage_layout_paths=[storage_layout_path]
    )
    archive_bytes = s[contract_file]["archive"]

    archive_path = Path("foo.zip")
    with archive_path.open("wb") as f:
        f.write(archive_bytes)

    assert zipfile.is_zipfile(archive_path)

    # compare compiling the two input bundles
    out = compile_files(
        [contract_file],
        ["integrity", "bytecode", "layout"],
        paths=search_paths,
        storage_layout_paths=[storage_layout_path],
    )
    out2 = compile_files([archive_path], ["integrity", "bytecode", "layout"])
    assert out[contract_file] == out2[archive_path]

    # tamper with the integrity sum
    archive_compiler_data = compiler_data_from_zip(archive_path, None, False)
    archive_compiler_data.expected_integrity_sum = TAMPERED_INTEGRITY_SUM

    with warnings.catch_warnings(record=True) as w:
        assert archive_compiler_data.integrity_sum is not None

    assert len(w) == 1, [s.message for s in w]
    assert str(w[0].message).startswith(INTEGRITY_WARNING.format(integrity=integrity))


def test_archive_b64_output(input_files):
    tmpdir, _, _, _, contract_file, _ = input_files
    search_paths = [".", tmpdir]

    out = compile_files(
        [contract_file], ["archive_b64", "integrity", "bytecode"], paths=search_paths
    )

    archive_b64 = out[contract_file].pop("archive_b64")

    archive_path = Path("foo.zip.b64")
    with archive_path.open("w") as f:
        f.write(archive_b64)

    # compare compiling the two input bundles
    out2 = compile_files([archive_path], ["integrity", "bytecode"])
    assert out[contract_file] == out2[archive_path]


def test_archive_compile_options(input_files):
    tmpdir, _, _, _, contract_file, _ = input_files
    search_paths = [".", tmpdir]

    options = ["abi_python", "json", "ast", "annotated_ast", "ir_json"]

    for option in options:
        out = compile_files([contract_file], ["archive_b64", option], paths=search_paths)

        archive_b64 = out[contract_file].pop("archive_b64")

        archive_path = Path("foo.zip.b64")
        with archive_path.open("w") as f:
            f.write(archive_b64)

        # compare compiling the two input bundles
        out2 = compile_files([archive_path], [option])

        if option in ["ast", "annotated_ast"]:
            # would have to normalize paths and imports, so just verify it compiles
            continue

        assert out[contract_file] == out2[archive_path]


format_options = [
    "bytecode",
    "bytecode_runtime",
    "blueprint_bytecode",
    "abi",
    "abi_python",
    "source_map",
    "source_map_runtime",
    "method_identifiers",
    "userdoc",
    "devdoc",
    "metadata",
    "combined_json",
    "layout",
    "ast",
    "annotated_ast",
    "interface",
    "external_interface",
    "opcodes",
    "opcodes_runtime",
    "ir",
    "ir_json",
    "ir_runtime",
    "asm",
    "integrity",
    "archive",
    "solc_json",
]


def test_compile_vyz_with_options(input_files):
    tmpdir, _, _, _, contract_file, _ = input_files
    search_paths = [".", tmpdir]

    for option in format_options:
        out_archive = compile_files([contract_file], ["archive"], paths=search_paths)

        archive = out_archive[contract_file].pop("archive")

        archive_path = Path("foo.zip.out.vyz")
        with archive_path.open("wb") as f:
            f.write(archive)

        # compare compiling the two input bundles
        out = compile_files([contract_file], [option], paths=search_paths)
        out2 = compile_files([archive_path], [option])

        if option in ["ast", "annotated_ast", "metadata"]:
            # would have to normalize paths and imports, so just verify it compiles
            continue

        if option in ["ir_runtime", "ir", "archive"]:
            # ir+ir_runtime is different due to being different compiler runs
            # archive is different due to different metadata (timestamps)
            continue

        assert out[contract_file] == out2[archive_path]


def test_archive_compile_simultaneous_options(input_files):
    tmpdir, _, _, _, contract_file, _ = input_files
    search_paths = [".", tmpdir]

    for option in format_options:
        with pytest.raises(ValueError) as e:
            _ = compile_files([contract_file], ["archive", option], paths=search_paths)

        err_opt = "archive"
        if option in ("combined_json", "solc_json"):
            err_opt = option

        assert f"If using {err_opt} it must be the only output format requested" in str(e.value)


def test_solc_json_output(input_files):
    tmpdir, _, _, storage_layout_path, contract_file, integrity = input_files
    search_paths = [".", tmpdir]

    out = compile_files(
        [contract_file],
        ["solc_json"],
        paths=search_paths,
        storage_layout_paths=[storage_layout_path],
    )
    json_input = out[contract_file]["solc_json"]

    # check that round-tripping solc_json thru standard json produces
    # the same as compiling directly
    json_out = compile_json(json_input)["contracts"]["contract.vy"]
    json_out_bytecode = json_out["contract"]["evm"]["bytecode"]["object"]
    json_out_layout = json_out["contract"]["layout"]["storage_layout"]

    out2 = compile_files(
        [contract_file],
        ["integrity", "bytecode", "layout"],
        paths=search_paths,
        storage_layout_paths=[storage_layout_path],
    )

    assert out2[contract_file]["bytecode"] == json_out_bytecode
    assert out2[contract_file]["layout"]["storage_layout"] == json_out_layout

    # tamper with the integrity sum
    json_input["integrity"] = TAMPERED_INTEGRITY_SUM
    _, warn_data = compile_from_input_dict(json_input)

    w = warn_data[Path("contract.vy")]
    assert len(w) == 1, [s.message for s in w]
    assert str(w[0].message).startswith(INTEGRITY_WARNING.format(integrity=integrity))


# maybe this belongs in tests/unit/compiler?
def test_integrity_sum(input_files):
    tmpdir, library_file, jsonabi_file, storage_layout_path, contract_file, integrity = input_files
    search_paths = [".", tmpdir]

    out = compile_files(
        [contract_file],
        ["integrity"],
        paths=search_paths,
        storage_layout_paths=[storage_layout_path],
    )

    assert out[contract_file]["integrity"] == integrity


# does this belong in tests/unit/compiler?
def test_archive_search_path(tmp_path_factory, make_file, chdir_tmp_path):
    lib1 = """
x: uint256
    """
    lib2 = """
y: uint256
    """
    dir1 = tmp_path_factory.mktemp("dir1")
    dir2 = tmp_path_factory.mktemp("dir2")
    make_file(dir1 / "lib.vy", lib1)
    make_file(dir2 / "lib.vy", lib2)

    main = """
import lib
    """
    pwd = Path(".")
    make_file(pwd / "main.vy", main)
    for search_paths in ([pwd, dir1, dir2], [pwd, dir2, dir1]):
        input_bundle = FilesystemInputBundle(search_paths)
        file_input = input_bundle.load_file("main.vy")

        # construct CompilerData manually
        compiler_data = CompilerData(file_input, input_bundle)
        output_bundle = OutputBundle(compiler_data)

        used_dir = search_paths[-1].stem  # either dir1 or dir2
        assert output_bundle.used_search_paths == [".", "0/" + used_dir]


def test_compile_interface_file(make_file):
    interface = """
@view
@external
def foo() -> String[1]:
    ...

@view
@external
def bar() -> String[1]:
    ...

@external
def baz() -> uint8:
    ...

    """
    file = make_file("interface.vyi", interface)
    compile_files([file], INTERFACE_OUTPUT_FORMATS)

    # check unallowed output formats
    for f in OUTPUT_FORMATS:
        if f in INTERFACE_OUTPUT_FORMATS:
            continue
        with pytest.raises(ValueError):
            compile_files([file], [f])
