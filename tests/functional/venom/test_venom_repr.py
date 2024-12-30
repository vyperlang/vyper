import copy
import glob
import textwrap

import pytest

from tests.venom_utils import assert_ctx_eq, parse_venom
from vyper.compiler import compile_code
from vyper.compiler.phases import generate_bytecode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.context import IRContext

"""
Check that venom text format round-trips through parser
"""


def get_example_vy_filenames():
    return glob.glob("**/*.vy", root_dir="examples/", recursive=True)


@pytest.mark.parametrize("vy_filename", get_example_vy_filenames())
def test_round_trip_examples(vy_filename, debug, optimize, compiler_settings, request):
    """
    Check all examples round trip
    """
    path = f"examples/{vy_filename}"
    with open(path) as f:
        vyper_source = f.read()

    if debug and optimize == OptimizationLevel.CODESIZE:
        # FIXME: some round-trips fail when debug is enabled due to labels
        # not getting pinned
        request.node.add_marker(pytest.mark.xfail(strict=False))

    _round_trip_helper(vyper_source, optimize, compiler_settings)


# pure vyper sources
vyper_sources = [
    """
    @external
    def _loop() -> uint256:
        res: uint256 = 9
        for i: uint256 in range(res, bound=10):
            res = res + i
        return res
        """
]


@pytest.mark.parametrize("vyper_source", vyper_sources)
def test_round_trip_sources(vyper_source, debug, optimize, compiler_settings, request):
    """
    Test vyper_sources round trip
    """
    vyper_source = textwrap.dedent(vyper_source)

    if debug and optimize == OptimizationLevel.CODESIZE:
        # FIXME: some round-trips fail when debug is enabled due to labels
        # not getting pinned
        request.node.add_marker(pytest.mark.xfail(strict=False))

    _round_trip_helper(vyper_source, optimize, compiler_settings)


def _round_trip_helper(vyper_source, optimize, compiler_settings):
    # helper function to test venom round-tripping thru the parser
    # use two helpers because run_passes_on and
    # generate_assembly_experimental are both destructive (mutating) on
    # the IRContext
    _helper1(vyper_source, optimize)
    _helper2(vyper_source, optimize, compiler_settings)


def _helper1(vyper_source, optimize):
    """
    Check that we are able to run passes on the round-tripped venom code
    and that it is valid (generates bytecode)
    """
    # note: compiling any later stage than bb_runtime like `asm` or
    # `bytecode` modifies the bb_runtime data structure in place and results
    # in normalization of the venom cfg (which breaks again make_ssa)
    out = compile_code(vyper_source, output_formats=["bb_runtime"])

    bb_runtime = out["bb_runtime"]
    venom_code = IRContext.__repr__(bb_runtime)

    ctx = parse_venom(venom_code)

    assert_ctx_eq(bb_runtime, ctx)

    # check it's valid to run venom passes+analyses
    # (note this breaks bytecode equality, in the future we should
    # test that separately)
    run_passes_on(ctx, optimize)

    # test we can generate assembly+bytecode
    asm = generate_assembly_experimental(ctx)
    generate_bytecode(asm, compiler_metadata=None)


def _helper2(vyper_source, optimize, compiler_settings):
    """
    Check that we can compile to bytecode, and without running venom passes,
    that the output bytecode is equal to going through the normal vyper pipeline
    """
    settings = copy.copy(compiler_settings)
    # bytecode equivalence only makes sense if we use venom pipeline
    settings.experimental_codegen = True

    out = compile_code(vyper_source, settings=settings, output_formats=["bb_runtime"])
    bb_runtime = out["bb_runtime"]
    venom_code = IRContext.__repr__(bb_runtime)

    ctx = parse_venom(venom_code)

    assert_ctx_eq(bb_runtime, ctx)

    # test we can generate assembly+bytecode
    asm = generate_assembly_experimental(ctx, optimize=optimize)
    bytecode = generate_bytecode(asm, compiler_metadata=None)

    out = compile_code(vyper_source, settings=settings, output_formats=["bytecode_runtime"])
    assert "0x" + bytecode.hex() == out["bytecode_runtime"]
