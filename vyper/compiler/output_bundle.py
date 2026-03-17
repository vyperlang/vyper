import importlib
import io
import json
import zipfile
from dataclasses import dataclass
from functools import cached_property
from pathlib import PurePath
from typing import Optional

from vyper.compiler.input_bundle import CompilerInput, JSONInput, _NotFound
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings
from vyper.exceptions import CompilerPanic
from vyper.utils import get_long_version, safe_relpath

# data structures and routines for constructing "output bundles",
# basically reproducible builds of a vyper contract, with varying
# formats. note this is similar but not exactly analogous to
# `input_bundle.py` -- the output bundle defined here contains more
# information.


def _anonymize(p: str):
    segments = []
    # replace ../../../a/b with 0/1/2/a/b
    for i, s in enumerate(PurePath(p).parts):
        if s == "..":
            segments.append(str(i))
        else:
            segments.append(s)

    # the way to get reliable paths which reproduce cross-platform is to use
    # posix style paths.
    # cf. https://stackoverflow.com/a/122485
    return PurePath(*segments).as_posix()


# data structure containing things that should be in an output bundle,
# which is some container containing the information required to
# reproduce a build
@dataclass
class OutputBundle:
    def __init__(self, compiler_data: CompilerData):
        self.compiler_data = compiler_data

    @cached_property
    def compilation_target(self):
        return self.compiler_data.compilation_target._metadata["type"]

    @cached_property
    def source_codes(self) -> dict[str, CompilerInput]:
        # return the `CompilerInput`s for this output bundle, as a dict
        # where the keys are the anonymized paths.
        # does not include builtins.
        import_analysis = self.compiler_data.resolved_imports

        inputs: list[CompilerInput] = import_analysis.compiler_inputs.copy()
        inputs = [inp for inp in inputs if not inp.from_builtin]

        # file input for the top level module; it's not in
        # import_analysis._compiler_inputs
        assert self.compiler_data.file_input not in inputs  # sanity
        inputs.append(self.compiler_data.file_input)

        sources = {}
        for c in inputs:
            path = safe_relpath(c.resolved_path)
            # note: there should be a 1:1 correspondence between
            # resolved_path and source_id, but for clarity use resolved_path
            # since it corresponds more directly to search path semantics.
            sources[_anonymize(path)] = c

        return sources

    @cached_property
    def compilation_target_path(self):
        p = PurePath(self.compiler_data.file_input.resolved_path)
        p = safe_relpath(p)
        return _anonymize(p)

    @cached_property
    def used_search_paths(self) -> list[str]:
        # report back which search paths were "actually used" in this
        # compilation run. this is useful mainly for aesthetic purposes,
        # because we don't need to see `/usr/lib/python` in the search path
        # if it is not used.
        # that being said, we are overly conservative. that is, we might
        # put search paths which are not actually used in the output.

        input_bundle = self.compiler_data.input_bundle

        search_paths = []
        for sp in input_bundle.search_paths:
            try:
                search_paths.append(input_bundle._normalize_path(sp))
            except _NotFound:
                # invalid / nonexistent path
                pass

        # preserve order of original search paths
        tmp = {sp: 0 for sp in search_paths}

        for c in self.source_codes.values():
            ok = False
            # recover the search path that was used for this CompilerInput.
            # note that it is not sufficient to thread the "search path that
            # was used" into CompilerInput because search_paths are modified
            # during compilation (so a search path which does not exist in
            # the original search_paths set could be used for a given file).
            for sp in reversed(search_paths):
                if c.resolved_path.is_relative_to(sp):
                    # don't break here. if there are more than 1 search path
                    # which could possibly match, we add all them to the
                    # output.
                    tmp[sp] += 1
                    ok = True

            # this shouldn't happen unless a file escapes its package,
            # *or* if we have a bug
            if not ok:
                raise CompilerPanic(f"Invalid path: {c.resolved_path}")

        sps = [sp for sp, count in tmp.items() if count > 0]
        assert len(sps) > 0

        return [_anonymize(safe_relpath(sp)) for sp in sps]


class OutputBundleWriter:
    def __init__(self, compiler_data: CompilerData):
        self.compiler_data = compiler_data

    @cached_property
    def bundle(self):
        return OutputBundle(self.compiler_data)

    def write_sources(self, sources: dict[str, CompilerInput]):
        raise NotImplementedError(f"write_sources: {self.__class__}")

    def write_storage_layout_overrides(
        self, compilation_target_path: str, storage_layout_override: JSONInput
    ):
        raise NotImplementedError(f"write_storage_layout_overrides: {self.__class__}")

    def write_search_paths(self, search_paths: list[str]):
        raise NotImplementedError(f"write_search_paths: {self.__class__}")

    def write_settings(self, settings: Optional[Settings]):
        raise NotImplementedError(f"write_settings: {self.__class__}")

    def write_integrity(self, integrity_sum: str):
        raise NotImplementedError(f"write_integrity: {self.__class__}")

    def write_compilation_target(self, targets: list[str]):
        raise NotImplementedError(f"write_compilation_target: {self.__class__}")

    def write_compiler_version(self, version: str):
        raise NotImplementedError(f"write_compiler_version: {self.__class__}")

    def output(self):
        raise NotImplementedError(f"output: {self.__class__}")

    def write(self):
        long_version = get_long_version()
        self.write_version(f"v{long_version}")
        self.write_compilation_target([self.bundle.compilation_target_path])
        self.write_search_paths(self.bundle.used_search_paths)
        self.write_settings(self.compiler_data.original_settings)
        self.write_integrity(self.compiler_data.integrity_sum)
        self.write_sources(self.bundle.source_codes)
        if self.compiler_data.storage_layout_override is not None:
            self.write_storage_layout_overrides(
                self.bundle.compilation_target_path, self.compiler_data.storage_layout_override
            )


class SolcJSONWriter(OutputBundleWriter):
    def __init__(self, compiler_data):
        super().__init__(compiler_data)

        self._output = {"language": "Vyper", "sources": {}, "settings": {"outputSelection": {}}}

    def write_sources(self, sources: dict[str, CompilerInput]):
        out = {}
        for path, c in sources.items():
            out[path] = {"content": c.contents, "sha256sum": c.sha256sum}

        self._output["sources"].update(out)

    def write_storage_layout_overrides(
        self, compilation_target_path: str, storage_layout_override: JSONInput
    ):
        # TODO: generalize to multiple files
        ret = {}
        path = _anonymize(str(storage_layout_override.path))
        ret[compilation_target_path] = {path: storage_layout_override.data}
        self._output["storage_layout_overrides"] = ret

    def write_search_paths(self, search_paths: list[str]):
        self._output["settings"]["search_paths"] = search_paths

    def write_settings(self, settings: Optional[Settings]):
        if settings is not None:
            s = settings.as_dict()
            if "evm_version" in s:
                s["evmVersion"] = s.pop("evm_version")
            if "experimental_codegen" in s:
                s["experimentalCodegen"] = s.pop("experimental_codegen")

            self._output["settings"].update(s)

    def write_integrity(self, integrity_sum: str):
        self._output["integrity"] = integrity_sum

    def write_compilation_target(self, targets: list[str]):
        for target in targets:
            self._output["settings"]["outputSelection"][target] = ["*"]

    def write_version(self, version):
        self._output["compiler_version"] = version

    def output(self):
        return self._output


def _get_compression_method():
    # try to find a compression library, if none are available then
    # fall back to ZIP_STORED
    # (note: these should all be on all modern systems and in particular
    # they should be in the build environment for our build artifacts,
    # but write the graceful fallback anyway because hygiene).
    try:
        importlib.import_module("zlib")
        return zipfile.ZIP_DEFLATED
    except ImportError:
        pass

    # fallback
    return zipfile.ZIP_STORED


class VyperArchiveWriter(OutputBundleWriter):
    def __init__(self, compiler_data: CompilerData):
        super().__init__(compiler_data)

        self._buf = io.BytesIO()
        method = _get_compression_method()
        self.archive = zipfile.ZipFile(self._buf, mode="w", compression=method, compresslevel=9)

    def __del__(self):
        # manually order the destruction of child objects.
        # cf. https://bugs.python.org/issue37773
        #     https://github.com/python/cpython/issues/81954
        del self.archive
        del self._buf

    def write_sources(self, sources: dict[str, CompilerInput]):
        for path, c in sources.items():
            self.archive.writestr(_anonymize(path), c.contents)

    def write_storage_layout_overrides(
        self, compilation_target_path: str, storage_layout_override: JSONInput
    ):
        path = _anonymize(str(storage_layout_override.path))
        self.archive.writestr(path, storage_layout_override.contents)
        self.archive.writestr(
            "MANIFEST/storage_layout.json", json.dumps({compilation_target_path: path})
        )

    def write_search_paths(self, search_paths: list[str]):
        self.archive.writestr("MANIFEST/searchpaths", "\n".join(search_paths))

    def write_settings(self, settings: Optional[Settings]):
        if settings is not None:
            self.archive.writestr("MANIFEST/settings.json", json.dumps(settings.as_dict()))
            self.archive.writestr("MANIFEST/cli_settings.txt", settings.as_cli())
        else:
            self.archive.writestr("MANIFEST/settings.json", json.dumps(None))
            self.archive.writestr("MANIFEST/cli_settings.txt", "")

    def write_integrity(self, integrity_sum: str):
        self.archive.writestr("MANIFEST/integrity", integrity_sum)

    def write_compilation_target(self, targets: list[str]):
        self.archive.writestr("MANIFEST/compilation_targets", "\n".join(targets))

    def write_version(self, version: str):
        self.archive.writestr("MANIFEST/compiler_version", version)

    def output(self):
        self.archive.close()

        # there is a race on windows where testzip() will return false
        # before closing. close it and then reopen to run testzip()
        s = zipfile.ZipFile(self._buf)
        assert s.testzip() is None
        del s  # garbage collector, cf. `__del__()` method.

        return self._buf.getvalue()
