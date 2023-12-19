import json
from pathlib import Path, PurePath

import pytest

from tests.utils import working_directory
from vyper.compiler.input_bundle import ABIInput, FileInput, FilesystemInputBundle, JSONInputBundle


# FilesystemInputBundle which uses same search path as make_file
@pytest.fixture
def input_bundle(tmp_path):
    return FilesystemInputBundle([tmp_path])


def test_load_file(make_file, input_bundle):
    filepath = make_file("foo.vy", "contents")

    file = input_bundle.load_file(Path("foo.vy"))

    assert isinstance(file, FileInput)
    assert file == FileInput(0, Path("foo.vy"), filepath, "contents")


def test_search_path_context_manager(make_file, tmp_path):
    ib = FilesystemInputBundle([])

    filepath = make_file("foo.vy", "contents")

    with pytest.raises(FileNotFoundError):
        # no search path given
        ib.load_file(Path("foo.vy"))

    with ib.search_path(tmp_path):
        file = ib.load_file(Path("foo.vy"))

    assert isinstance(file, FileInput)
    assert file == FileInput(0, Path("foo.vy"), filepath, "contents")


def test_search_path_precedence(make_file, tmp_path, tmp_path_factory, input_bundle):
    # test search path precedence.
    # most recent search path is the highest precedence
    tmpdir = tmp_path_factory.mktemp("some_directory")
    tmpdir2 = tmp_path_factory.mktemp("some_other_directory")

    filepaths = []
    for i, directory in enumerate([tmp_path, tmpdir, tmpdir2]):
        path = directory / "foo.vy"
        with path.open("w") as f:
            f.write(f"contents {i}")
        filepaths.append(path)

    ib = FilesystemInputBundle([tmp_path, tmpdir, tmpdir2])

    file = ib.load_file("foo.vy")

    assert isinstance(file, FileInput)
    assert file == FileInput(0, "foo.vy", filepaths[2], "contents 2")

    with ib.search_path(tmpdir):
        file = ib.load_file("foo.vy")

        assert isinstance(file, FileInput)
        assert file == FileInput(1, "foo.vy", filepaths[1], "contents 1")


# special rules for handling json files
def test_load_abi(make_file, input_bundle, tmp_path):
    contents = json.dumps("some string")

    path = make_file("foo.json", contents)

    file = input_bundle.load_file("foo.json")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(0, "foo.json", path, "some string")

    # suffix doesn't matter
    path = make_file("foo.txt", contents)
    file = input_bundle.load_file("foo.txt")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(1, "foo.txt", path, "some string")


# check that unique paths give unique source ids
def test_source_id_file_input(make_file, input_bundle, tmp_path):
    foopath = make_file("foo.vy", "contents")
    barpath = make_file("bar.vy", "contents 2")

    file = input_bundle.load_file("foo.vy")
    assert file.source_id == 0
    assert file == FileInput(0, "foo.vy", foopath, "contents")

    file2 = input_bundle.load_file("bar.vy")
    # source id increments
    assert file2.source_id == 1
    assert file2 == FileInput(1, "bar.vy", barpath, "contents 2")

    file3 = input_bundle.load_file("foo.vy")
    assert file3.source_id == 0
    assert file3 == FileInput(0, "foo.vy", foopath, "contents")

    # test source id is stable across different search paths
    with working_directory(tmp_path):
        with input_bundle.search_path(Path(".")):
            file4 = input_bundle.load_file("foo.vy")
            assert file4.source_id == 0
            assert file4 == FileInput(0, "foo.vy", foopath, "contents")

    # test source id is stable even when requested filename is different
    with working_directory(tmp_path.parent):
        with input_bundle.search_path(Path(".")):
            file5 = input_bundle.load_file(Path(tmp_path.stem) / "foo.vy")
            assert file5.source_id == 0
            assert file5 == FileInput(0, Path(tmp_path.stem) / "foo.vy", foopath, "contents")


# check that unique paths give unique source ids
def test_source_id_json_input(make_file, input_bundle, tmp_path):
    contents = json.dumps("some string")
    contents2 = json.dumps(["some list"])

    foopath = make_file("foo.json", contents)

    barpath = make_file("bar.json", contents2)

    file = input_bundle.load_file("foo.json")
    assert isinstance(file, ABIInput)
    assert file == ABIInput(0, "foo.json", foopath, "some string")

    file2 = input_bundle.load_file("bar.json")
    assert isinstance(file2, ABIInput)
    assert file2 == ABIInput(1, "bar.json", barpath, ["some list"])

    file3 = input_bundle.load_file("foo.json")
    assert file3.source_id == 0
    assert file3 == ABIInput(0, "foo.json", foopath, "some string")

    # test source id is stable across different search paths
    with working_directory(tmp_path):
        with input_bundle.search_path(Path(".")):
            file4 = input_bundle.load_file("foo.json")
            assert file4.source_id == 0
            assert file4 == ABIInput(0, "foo.json", foopath, "some string")

    # test source id is stable even when requested filename is different
    with working_directory(tmp_path.parent):
        with input_bundle.search_path(Path(".")):
            file5 = input_bundle.load_file(Path(tmp_path.stem) / "foo.json")
            assert file5.source_id == 0
            assert file5 == ABIInput(0, Path(tmp_path.stem) / "foo.json", foopath, "some string")


# test some pathological case where the file changes underneath
def test_mutating_file_source_id(make_file, input_bundle, tmp_path):
    foopath = make_file("foo.vy", "contents")

    file = input_bundle.load_file("foo.vy")
    assert file.source_id == 0
    assert file == FileInput(0, "foo.vy", foopath, "contents")

    foopath = make_file("foo.vy", "new contents")

    file = input_bundle.load_file("foo.vy")
    # source id hasn't changed, even though contents have
    assert file.source_id == 0
    assert file == FileInput(0, "foo.vy", foopath, "new contents")


# test the os.normpath behavior of symlink
# (slightly pathological, for illustration's sake)
def test_load_file_symlink(make_file, input_bundle, tmp_path, tmp_path_factory):
    dir1 = tmp_path / "first"
    dir2 = tmp_path / "second"
    symlink = tmp_path / "symlink"

    dir1.mkdir()
    dir2.mkdir()
    symlink.symlink_to(dir2, target_is_directory=True)

    outer_path = tmp_path / "foo.vy"
    with outer_path.open("w") as f:
        f.write("contents of the outer directory")

    inner_path = dir1 / "foo.vy"
    with inner_path.open("w") as f:
        f.write("contents of the inner directory")

    # symlink rules would be:
    # base/symlink/../foo.vy =>
    # base/first/second/../foo.vy =>
    # base/first/foo.vy
    # normpath would be base/symlink/../foo.vy =>
    # base/foo.vy
    to_load = symlink / ".." / "foo.vy"
    file = input_bundle.load_file(to_load)

    assert file == FileInput(0, to_load, outer_path.resolve(), "contents of the outer directory")


def test_json_input_bundle_basic():
    files = {PurePath("foo.vy"): {"content": "some text"}}
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    file = input_bundle.load_file(PurePath("foo.vy"))
    assert file == FileInput(0, PurePath("foo.vy"), PurePath("foo.vy"), "some text")


def test_json_input_bundle_normpath():
    contents = "some text"
    files = {PurePath("foo/../bar.vy"): {"content": contents}}
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    barpath = PurePath("bar.vy")

    expected = FileInput(0, barpath, barpath, contents)

    file = input_bundle.load_file(PurePath("bar.vy"))
    assert file == expected

    file = input_bundle.load_file(PurePath("baz/../bar.vy"))
    assert file == FileInput(0, PurePath("baz/../bar.vy"), barpath, contents)

    file = input_bundle.load_file(PurePath("./bar.vy"))
    assert file == FileInput(0, PurePath("./bar.vy"), barpath, contents)

    with input_bundle.search_path(PurePath("foo")):
        file = input_bundle.load_file(PurePath("../bar.vy"))
        assert file == FileInput(0, PurePath("../bar.vy"), barpath, contents)


def test_json_input_abi():
    some_abi = ["some abi"]
    some_abi_str = json.dumps(some_abi)
    foopath = PurePath("foo.json")
    barpath = PurePath("bar.txt")
    files = {foopath: {"abi": some_abi}, barpath: {"content": some_abi_str}}
    input_bundle = JSONInputBundle(files, [PurePath(".")])

    file = input_bundle.load_file(foopath)
    assert file == ABIInput(0, foopath, foopath, some_abi)

    file = input_bundle.load_file(barpath)
    assert file == ABIInput(1, barpath, barpath, some_abi)
