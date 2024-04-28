# not an entry point!
# utility functions to handle compiling from a "vyper archive"

import base64
import binascii
import io
import zipfile
from pathlib import PurePath

from vyper.compiler import compile_from_file_input
from vyper.compiler.input_bundle import FileInput, ZipInputBundle
from vyper.exceptions import BadArchive


class NotZipInput(Exception):
    pass


def compile_from_zip(file_name, output_formats, settings, no_bytecode_metadata):
    with open(file_name, "rb") as f:
        bcontents = f.read()

    try:
        buf = io.BytesIO(bcontents)
        archive = zipfile.ZipFile(buf, mode="r")
    except zipfile.BadZipFile as e1:
        try:
            # `validate=False` - tools like base64 can generate newlines
            # for readability. validate=False does the "correct" thing and
            # simply ignores these
            bcontents = base64.b64decode(bcontents, validate=False)
            buf = io.BytesIO(bcontents)
            archive = zipfile.ZipFile(buf, mode="r")
        except (zipfile.BadZipFile, binascii.Error):
            raise NotZipInput() from e1

    fcontents = archive.read("MANIFEST/compilation_targets").decode("utf-8")
    compilation_targets = fcontents.splitlines()

    if len(compilation_targets) != 1:
        raise BadArchive("Multiple compilation targets not supported!")

    input_bundle = ZipInputBundle(archive)

    mainpath = PurePath(compilation_targets[0])
    file = input_bundle.load_file(mainpath)
    assert isinstance(file, FileInput)  # mypy hint

    # TODO: read settings and merge them
    # TODO: validate integrity sum (probably in CompilerData)
    return compile_from_file_input(
        file,
        input_bundle=input_bundle,
        output_formats=output_formats,
        settings=settings,
        no_bytecode_metadata=no_bytecode_metadata,
    )
