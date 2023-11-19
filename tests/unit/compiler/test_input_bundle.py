import json
from pathlib import Path, PurePath

import pytest

from vyper.compiler.input_bundle import ABIInput, FileInput, FilesystemInputBundle, JSONInputBundle


# FilesystemInputBundle which uses same search path as make_file
@pytest.fixture
def input_bundle(tmp_path):
    return FilesystemInputBundle([tmp_path])


def test_load_file(make_file, input_bundle, tmp_path):
    make_file("foo.vy", "contents")

    file = input_bundle.load_file(Path("foo.vy"))

    assert isinstance(file, FileInput)
    assert file == FileInput(0, tmp_path / Path("foo.vy"), "contents")


def test_search_path_context_manager(make_file, tmp_path):
    ib = FilesystemInputBundle([])

    make_file("foo.vy", "contents")

    with pytest.raises(FileNotFoundError):
        # no search path given
        ib.load_file(Path("foo.vy"))

    with ib.search_path(tmp_path):
        file = ib.load_file(Path("foo.vy"))

    assert isinstance(file, FileInput)
    assert file == FileInput(0, tmp_path / Path("foo.vy"), "contents")


def test_search_path_precedence(make_file, tmp_path, tmp_path_factory, input_bundle):
    # test search path precedence.
    # most recent search path is the highest precedence
    tmpdir = tmp_path_factory.mktemp("some_directory")
    tmpdir2 = tmp_path_factory.mktemp("some_other_directory")

    for i, directory in enumerate([tmp_path, tmpdir, tmpdir2]):
        with (directory / "foo.vy").open("w") as f:
            f.write(f"contents {i}")

    ib = FilesystemInputBundle([tmp_path, tmpdir, tmpdir2])

    file = ib.load_file("foo.vy")

    assert isinstance(file, FileInput)
    assert file == FileInput(0, tmpdir2 / "foo.vy", "contents 2")

    with ib.search_path(tmpdir):
        file = ib.load_file("foo.vy")

        assert isinstance(file, FileInput)
        assert file == FileInput(1, tmpdir / "foo.vy", "contents 1")


# special rules for handling json files
def test_load_abi(make_file, input_bundle, tmp_path):
    contents = json.dumps("some string")

    make_file("foo.json", contents)

    file = input_bundle.load_file("foo.json")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(0, tmp_path / "foo.json", "some string")

    # suffix doesn't matter
    make_file("foo.txt", contents)

    file = input_bundle.load_file("foo.txt")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(1, tmp_path / "foo.txt", "some string")


# check that unique paths give unique source ids
def test_source_id_file_input(make_file, input_bundle, tmp_path):
    make_file("foo.vy", "contents")
    make_file("bar.vy", "contents 2")

    file = input_bundle.load_file("foo.vy")
    assert file.source_id == 0
    assert file == FileInput(0, tmp_path / "foo.vy", "contents")

    file2 = input_bundle.load_file("bar.vy")
    # source id increments
    assert file2.source_id == 1
    assert file2 == FileInput(1, tmp_path / "bar.vy", "contents 2")

    file3 = input_bundle.load_file("foo.vy")
    assert file3.source_id == 0
    assert file3 == FileInput(0, tmp_path / "foo.vy", "contents")


# check that unique paths give unique source ids
def test_source_id_json_input(make_file, input_bundle, tmp_path):
    contents = json.dumps("some string")
    contents2 = json.dumps(["some list"])

    make_file("foo.json", contents)

    make_file("bar.json", contents2)

    file = input_bundle.load_file("foo.json")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(0, tmp_path / "foo.json", "some string")

    file2 = input_bundle.load_file("bar.json")
    assert isinstance(file2, ABIInput)
    assert file2 == ABIInput(1, tmp_path / "bar.json", ["some list"])

    file3 = input_bundle.load_file("foo.json")
    assert isinstance(file3, ABIInput)
    assert file3 == ABIInput(0, tmp_path / "foo.json", "some string")


# test some pathological case where the file changes underneath
def test_mutating_file_source_id(make_file, input_bundle, tmp_path):
    make_file("foo.vy", "contents")

    file = input_bundle.load_file("foo.vy")
    assert file.source_id == 0
    assert file == FileInput(0, tmp_path / "foo.vy", "contents")

    make_file("foo.vy", "new contents")

    file = input_bundle.load_file("foo.vy")
    # source id hasn't changed, even though contents have
    assert file.source_id == 0
    assert file == FileInput(0, tmp_path / "foo.vy", "new contents")


# test the os.normpath behavior of symlink
# (slightly pathological, for illustration's sake)
def test_load_file_symlink(make_file, input_bundle, tmp_path, tmp_path_factory):
    dir1 = tmp_path / "first"
    dir2 = tmp_path / "second"
    symlink = tmp_path / "symlink"

    dir1.mkdir()
    dir2.mkdir()
    symlink.symlink_to(dir2, target_is_directory=True)

    with (tmp_path / "foo.vy").open("w") as f:
        f.write("contents of the upper directory")

    with (dir1 / "foo.vy").open("w") as f:
        f.write("contents of the inner directory")

    # symlink rules would be:
    # base/symlink/../foo.vy =>
    # base/first/second/../foo.vy =>
    # base/first/foo.vy
    # normpath would be base/symlink/../foo.vy =>
    # base/foo.vy
    file = input_bundle.load_file(symlink / ".." / "foo.vy")

    assert file == FileInput(0, tmp_path / "foo.vy", "contents of the upper directory")


def test_json_input_bundle_basic():
    files = {PurePath("foo.vy"): {"content": "some text"}}
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    file = input_bundle.load_file(PurePath("foo.vy"))
    assert file == FileInput(0, PurePath("foo.vy"), "some text")


def test_json_input_bundle_normpath():
    files = {PurePath("foo/../bar.vy"): {"content": "some text"}}
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    expected = FileInput(0, PurePath("bar.vy"), "some text")

    file = input_bundle.load_file(PurePath("bar.vy"))
    assert file == expected

    file = input_bundle.load_file(PurePath("baz/../bar.vy"))
    assert file == expected

    file = input_bundle.load_file(PurePath("./bar.vy"))
    assert file == expected

    with input_bundle.search_path(PurePath("foo")):
        file = input_bundle.load_file(PurePath("../bar.vy"))
        assert file == expected


def test_json_input_abi():
    some_abi = ["some abi"]
    some_abi_str = json.dumps(some_abi)
    files = {
        PurePath("foo.json"): {"abi": some_abi},
        PurePath("bar.txt"): {"content": some_abi_str},
    }
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    file = input_bundle.load_file(PurePath("foo.json"))
    assert file == ABIInput(0, PurePath("foo.json"), some_abi)

    file = input_bundle.load_file(PurePath("bar.txt"))
    assert file == ABIInput(1, PurePath("bar.txt"), some_abi)
