import base64
import io
import warnings
import zipfile

import pytest

from vyper import compile_code
from vyper.cli.compile_archive import compiler_data_from_zip
from vyper.compiler.input_bundle import ZipInputBundle
from vyper.exceptions import BadArchive
from vyper.utils import sha256sum


def make_archive(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
            for name, contents in members:
                archive.writestr(name, contents)
    return buf.getvalue()


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("prefix", ["", "./"])
def test_valid_archive(tmp_path, encoded, prefix):
    source = "@external\ndef foo() -> uint256:\n    return 42\n"
    members = [
        ("MANIFEST/", ""),
        ("MANIFEST/searchpaths", "."),
        ("MANIFEST/compilation_targets", "src/main.vy"),
        ("MANIFEST/settings.json", "{}"),
        ("MANIFEST/integrity", sha256sum(sha256sum(source))),
        ("src/", ""),
        ("src/main.vy", source),
        ("src/Main.vy", "# case-sensitive namespace"),
        ("src/café.vy", "# Unicode names are valid"),
        ("/absolute.vy", "# absolute POSIX names are valid"),
        ("C:/drive.vy", "# drive-prefixed POSIX names are valid"),
    ]
    contents = make_archive([(prefix + name, value) for name, value in members])
    path = tmp_path / "input.vyz"
    path.write_bytes(base64.b64encode(contents) if encoded else contents)
    data = compiler_data_from_zip(path, None, False)
    assert data.source_code == source
    assert data.bytecode.hex() == compile_code(source, output_formats=["bytecode"])["bytecode"][2:]
    bundle = data.input_bundle
    assert bundle.load_file("src/./main.vy").source_id == bundle.load_file("src/main.vy").source_id


@pytest.mark.parametrize("entrypoint", ["bundle", "cli", "base64"])
@pytest.mark.parametrize(
    "names",
    [
        ["main.vy", "main.vy"],
        ["MANIFEST/compilation_targets", "MANIFEST/compilation_targets"],
        ["MANIFEST/searchpaths", "MANIFEST/searchpaths"],
        ["main.vy", "./main.vy"],
        ["./main.vy", "main.vy"],
        ["src/main.vy", "src/./main.vy"],
        ["src/main.vy", "src//main.vy"],
        ["src", "src/"],
        ["MANIFEST/compilation_targets", "./MANIFEST/compilation_targets"],
    ],
)
def test_duplicate_archive_members(tmp_path, monkeypatch, entrypoint, names):
    contents = make_archive([(name, str(i)) for i, name in enumerate(names)])
    assert_rejected_before_read(tmp_path, monkeypatch, entrypoint, contents, "Duplicate archive")


@pytest.mark.parametrize("entrypoint", ["bundle", "cli", "base64"])
@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "./",
        "../main.vy",
        "src/../main.vy",
        "src/../../main.vy",
        "src/..",
        "src\\main.vy",
        "C:\\main.vy",
        "main.vy\x00suffix",
    ],
)
def test_invalid_archive_member(tmp_path, monkeypatch, entrypoint, name):
    # Substitute a same-length byte in both ZIP headers: writestr truncates NULs.
    contents = make_archive([("unused.vy", ""), (name.replace("\x00", "!"), "")])
    if "\x00" in name:
        contents = contents.replace(name.replace("\x00", "!").encode(), name.encode())
    assert_rejected_before_read(tmp_path, monkeypatch, entrypoint, contents, "Invalid archive")


def assert_rejected_before_read(tmp_path, monkeypatch, entrypoint, contents, message):
    def unexpected_read(*args, **kwargs):
        pytest.fail("Archive member contents read before namespace validation")

    monkeypatch.setattr(zipfile.ZipFile, "open", unexpected_read)
    with pytest.raises(BadArchive, match=message):
        if entrypoint == "bundle":
            with zipfile.ZipFile(io.BytesIO(contents)) as archive:
                ZipInputBundle(archive)
        else:
            path = tmp_path / "input.vyz"
            path.write_bytes(base64.b64encode(contents) if entrypoint == "base64" else contents)
            compiler_data_from_zip(path, None, False)
