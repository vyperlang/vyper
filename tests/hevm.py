import contextlib
import subprocess

import pytest

from tests.venom_utils import parse_from_basic_block
from vyper.ir.compile_ir import assembly_to_evm
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.analysis.fcg import FCGAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral
from vyper.venom.passes import (
    CFGNormalization,
    ConcretizeMemLocPass,
    LowerDloadPass,
    SimplifyCFGPass,
    SingleUseExpansion,
)
from vyper.venom.venom_to_assembly import VenomCompiler

HAS_HEVM: bool = False


def has_hevm():
    return HAS_HEVM


def _prep_hevm_venom(venom_source_code, verbose=False):
    ctx = parse_from_basic_block(venom_source_code)
    return _prep_hevm_venom_ctx(ctx)


# small class to ensure correct function traversal order and help with
# allocation
class _FunctionVisitor:
    num_calldataloads = 0
    visited: set

    def __init__(self):
        self.visited = set()


def _prep_hevm_venom_ctx(ctx, verbose=False):
    visitor = _FunctionVisitor()
    _prep_hevm_venom_fn(ctx.entry_function, visitor)

    compiler = VenomCompiler(ctx)
    asm = compiler.generate_evm_assembly(no_optimize=False)
    return assembly_to_evm(asm)[0].hex()


def _prep_hevm_venom_fn(fn, visitor):
    ac = IRAnalysesCache(fn)
    fcg = ac.force_analysis(FCGAnalysis)
    if fn in visitor.visited:
        return
    visitor.visited.add(fn)
    for next_fn in fcg.get_callees(fn):
        _prep_hevm_venom_fn(next_fn, visitor)

    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            # transform `source` instructions into "symbolic" values for
            # hevm via calldataload
            if inst.opcode == "source":
                # hevm limit: 256 bytes of symbolic calldata
                assert visitor.num_calldataloads < 8

                inst.opcode = "calldataload"
                inst.operands = [IRLiteral(visitor.num_calldataloads * 32)]
                visitor.num_calldataloads += 1

        term = bb.instructions[-1]
        # test convention, terminate by `sink`ing the variables
        # you want to check
        if term.opcode != "sink":
            continue

        # testing convention: first 256 bytes can be symbolically filled
        # with calldata
        RETURN_START = 256

        num_return_values = 0
        for op in term.operands:
            ptr = IRLiteral(RETURN_START + num_return_values * 32)
            new_inst = IRInstruction("mstore", [op, ptr])
            bb.insert_instruction(new_inst, index=-1)
            num_return_values += 1

        # return 0, 32 * num_variables
        term.opcode = "return"
        term.operands = [IRLiteral(num_return_values * 32), IRLiteral(RETURN_START)]

    # required for venom_to_assembly right now but should be removed
    SimplifyCFGPass(ac, fn).run_pass()

    # requirements for venom_to_assembly
    LowerDloadPass(ac, fn).run_pass()
    ConcretizeMemLocPass(ac, fn).run_pass()
    SingleUseExpansion(ac, fn).run_pass()
    CFGNormalization(ac, fn).run_pass()


def hevm_check_venom(pre, post, verbose=False):
    if not has_hevm():
        return

    # perform hevm equivalence check
    if verbose:
        print("HEVM COMPARE.")
        print("BEFORE:", pre)
        print("OPTIMIZED:", post)
    bytecode1 = _prep_hevm_venom(pre, verbose=verbose)
    bytecode2 = _prep_hevm_venom(post, verbose=verbose)

    hevm_check_bytecode(bytecode1, bytecode2, verbose=verbose)


def hevm_check_venom_ctx(pre, post, verbose=False):
    if not has_hevm():
        return

    # perform hevm equivalence check
    if verbose:
        print("HEVM COMPARE.")
        print("BEFORE:", pre)
        print("OPTIMIZED:", post)
    bytecode1 = _prep_hevm_venom_ctx(pre, verbose=verbose)
    bytecode2 = _prep_hevm_venom_ctx(post, verbose=verbose)

    hevm_check_bytecode(bytecode1, bytecode2, verbose=verbose)


@contextlib.contextmanager
def hevm_raises():
    if not has_hevm():
        pytest.skip("skipping because `--hevm` was not specified")

    with pytest.raises(subprocess.CalledProcessError) as e:
        yield e


# use hevm to check equality between two bytecodes (hex)
def hevm_check_bytecode(bytecode1, bytecode2, verbose=False, addl_args: list = None):
    # debug:
    if verbose:
        print("RUN HEVM:")
        print(bytecode1)
        print(bytecode2)

    subp_args = ["hevm", "equivalence", "--code-a", bytecode1, "--code-b", bytecode2]
    subp_args.extend(["--num-solvers", "1"])
    if addl_args:
        subp_args.extend([*addl_args])

    res = subprocess.run(
        subp_args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    assert not res.stderr, res.stderr  # hevm does not print to stderr
    # TODO: get hevm team to provide a way to promote warnings to errors
    assert "WARNING" not in res.stdout, res.stdout
    assert "issues" not in res.stdout
    if verbose:
        print(res.stdout)
