import contextlib
import sys
from pathlib import Path

import pytest

from tests.utils import working_directory
from vyper.cli.vyper_compile import compile_files


def test_combined_json_keys(tmp_path, make_file):
    make_file("bar.vy", "")

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
    compile_data = compile_files(["bar.vy"], ["combined_json"], paths=[tmp_path])

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
def test_import_same_folder(import_stmt, alias, tmp_path, make_file):
    foo = "contracts/foo.vy"
    make_file("contracts/foo.vy", CONTRACT_CODE.format(import_stmt=import_stmt, alias=alias))
    make_file("contracts/IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"], paths=[tmp_path])


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
def test_import_subfolder(import_stmt, alias, tmp_path, make_file):
    foo = make_file(
        "contracts/foo.vy", (CONTRACT_CODE.format(import_stmt=import_stmt, alias=alias))
    )
    make_file("contracts/other/IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"], paths=[tmp_path])


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

    assert compile_files([foo], ["combined_json"], paths=[tmp_path])


def test_import_parent_folder(tmp_path, make_file):
    foo = make_file(
        "contracts/baz/foo.vy",
        CONTRACT_CODE.format(import_stmt="from ... import IFoo", alias="IFoo"),
    )
    make_file("IFoo.vyi", INTERFACE_CODE)

    assert compile_files([foo], ["combined_json"], paths=[tmp_path])

    # perform relative import outside of base folder
    compile_files([foo], ["combined_json"], paths=[tmp_path / "contracts"])


def test_import_search_paths(tmp_path, make_file):
    with working_directory(tmp_path):
        contract_code = CONTRACT_CODE.format(import_stmt="from utils import IFoo", alias="IFoo")
        contract_filename = "dir1/baz/foo.vy"
        interface_filename = "dir2/utils/IFoo.vyi"
        make_file(interface_filename, INTERFACE_CODE)
        make_file(contract_filename, contract_code)

        assert compile_files([contract_filename], ["combined_json"], paths=["dir2"])


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

    assert compile_files([meta], ["combined_json"], paths=[tmp_path])


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

    assert compile_files([baz], ["combined_json"], paths=[tmp_path])


def test_local_namespace(make_file, tmp_path):
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

    assert compile_files(paths, ["combined_json"], paths=[tmp_path])


def test_compile_outside_root_path(tmp_path, make_file):
    # absolute paths relative to "."
    make_file("ifoo.vyi", INTERFACE_CODE)
    foo = make_file("foo.vy", CONTRACT_CODE.format(import_stmt="import ifoo as IFoo", alias="IFoo"))

    assert compile_files([foo], ["combined_json"], paths=None)


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


def test_import_sys_path(tmp_path_factory, make_file):
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
    tmpdir = tmp_path_factory.mktemp("test-sys-path")
    with open(tmpdir / "lib.vy", "w") as f:
        f.write(library_source)

    contract_file = make_file("contract.vy", contract_source)
    with mock_sys_path(tmpdir):
        assert compile_files([contract_file], ["combined_json"]) is not None
