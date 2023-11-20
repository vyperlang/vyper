from pathlib import Path

import pytest

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
    compile_data = compile_files(["bar.vy"], ["combined_json"], root_folder=tmp_path)

    assert set(compile_data.keys()) == {Path("bar.vy"), "version"}
    assert set(compile_data[Path("bar.vy")].keys()) == combined_keys


def test_invalid_root_path():
    with pytest.raises(FileNotFoundError):
        compile_files([], [], root_folder="path/that/does/not/exist")


FOO_CODE = """
{}

struct FooStruct:
    foo_: uint256

@external
def foo() -> FooStruct:
    return FooStruct({{foo_: 13}})

@external
def bar(a: address) -> FooStruct:
    return {}(a).bar()
"""

BAR_CODE = """
struct FooStruct:
    foo_: uint256
@external
def bar() -> FooStruct:
    return FooStruct({foo_: 13})
"""


SAME_FOLDER_IMPORT_STMT = [
    ("import Bar as Bar", "Bar"),
    ("import contracts.Bar as Bar", "Bar"),
    ("from . import Bar", "Bar"),
    ("from contracts import Bar", "Bar"),
    ("from ..contracts import Bar", "Bar"),
    ("from . import Bar as FooBar", "FooBar"),
    ("from contracts import Bar as FooBar", "FooBar"),
    ("from ..contracts import Bar as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt,alias", SAME_FOLDER_IMPORT_STMT)
def test_import_same_folder(import_stmt, alias, tmp_path, make_file):
    foo = "contracts/foo.vy"
    make_file("contracts/foo.vy", FOO_CODE.format(import_stmt, alias))
    make_file("contracts/Bar.vy", BAR_CODE)

    assert compile_files([foo], ["combined_json"], root_folder=tmp_path)


SUBFOLDER_IMPORT_STMT = [
    ("import other.Bar as Bar", "Bar"),
    ("import contracts.other.Bar as Bar", "Bar"),
    ("from other import Bar", "Bar"),
    ("from contracts.other import Bar", "Bar"),
    ("from .other import Bar", "Bar"),
    ("from ..contracts.other import Bar", "Bar"),
    ("from other import Bar as FooBar", "FooBar"),
    ("from contracts.other import Bar as FooBar", "FooBar"),
    ("from .other import Bar as FooBar", "FooBar"),
    ("from ..contracts.other import Bar as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt, alias", SUBFOLDER_IMPORT_STMT)
def test_import_subfolder(import_stmt, alias, tmp_path, make_file):
    foo = make_file("contracts/foo.vy", (FOO_CODE.format(import_stmt, alias)))
    make_file("contracts/other/Bar.vy", BAR_CODE)

    assert compile_files([foo], ["combined_json"], root_folder=tmp_path)


OTHER_FOLDER_IMPORT_STMT = [
    ("import interfaces.Bar as Bar", "Bar"),
    ("from interfaces import Bar", "Bar"),
    ("from ..interfaces import Bar", "Bar"),
    ("from interfaces import Bar as FooBar", "FooBar"),
    ("from ..interfaces import Bar as FooBar", "FooBar"),
]


@pytest.mark.parametrize("import_stmt, alias", OTHER_FOLDER_IMPORT_STMT)
def test_import_other_folder(import_stmt, alias, tmp_path, make_file):
    foo = make_file("contracts/foo.vy", FOO_CODE.format(import_stmt, alias))
    make_file("interfaces/Bar.vy", BAR_CODE)

    assert compile_files([foo], ["combined_json"], root_folder=tmp_path)


def test_import_parent_folder(tmp_path, make_file):
    foo = make_file("contracts/baz/foo.vy", FOO_CODE.format("from ... import Bar", "Bar"))
    make_file("Bar.vy", BAR_CODE)

    assert compile_files([foo], ["combined_json"], root_folder=tmp_path)

    # perform relative import outside of base folder
    compile_files([foo], ["combined_json"], root_folder=tmp_path / "contracts")


META_IMPORT_STMT = [
    "import Meta as Meta",
    "import contracts.Meta as Meta",
    "from . import Meta",
    "from contracts import Meta",
]


@pytest.mark.parametrize("import_stmt", META_IMPORT_STMT)
def test_import_self_interface(import_stmt, tmp_path, make_file):
    # a contract can access its derived interface by importing itself
    code = f"""
{import_stmt}

struct FooStruct:
    foo_: uint256

@external
def know_thyself(a: address) -> FooStruct:
    return Meta(a).be_known()

@external
def be_known() -> FooStruct:
    return FooStruct({{foo_: 42}})
    """
    meta = make_file("contracts/Meta.vy", code)

    assert compile_files([meta], ["combined_json"], root_folder=tmp_path)


DERIVED_IMPORT_STMT_BAZ = ["import Foo as Foo", "from . import Foo"]

DERIVED_IMPORT_STMT_FOO = ["import Bar as Bar", "from . import Bar"]


@pytest.mark.parametrize("import_stmt_baz", DERIVED_IMPORT_STMT_BAZ)
@pytest.mark.parametrize("import_stmt_foo", DERIVED_IMPORT_STMT_FOO)
def test_derived_interface_imports(import_stmt_baz, import_stmt_foo, tmp_path, make_file):
    # contracts-as-interfaces should be able to contain import statements
    baz_code = f"""
{import_stmt_baz}

struct FooStruct:
    foo_: uint256

@external
def foo(a: address) -> FooStruct:
    return Foo(a).foo()

@external
def bar(_foo: address, _bar: address) -> FooStruct:
    return Foo(_foo).bar(_bar)
    """

    make_file("Foo.vy", FOO_CODE.format(import_stmt_foo, "Bar"))
    make_file("Bar.vy", BAR_CODE)
    baz = make_file("Baz.vy", baz_code)

    assert compile_files([baz], ["combined_json"], root_folder=tmp_path)


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

    for file_name in ("foo.vy", "bar.vy"):
        make_file(file_name, BAR_CODE)

    assert compile_files(paths, ["combined_json"], root_folder=tmp_path)


def test_compile_outside_root_path(tmp_path, make_file):
    # absolute paths relative to "."
    foo = make_file("foo.vy", FOO_CODE.format("import bar as Bar", "Bar"))
    bar = make_file("bar.vy", BAR_CODE)

    assert compile_files([foo, bar], ["combined_json"], root_folder=".")
