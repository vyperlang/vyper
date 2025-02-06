import subprocess

from tests.venom_utils import parse_from_basic_block
from vyper.ir.compile_ir import assembly_to_evm
from vyper.venom import StoreExpansionPass, VenomCompiler
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRInstruction, IRLiteral

HAS_HEVM: bool = False


def _prep_hevm_venom(venom_source_code):
    ctx = parse_from_basic_block(venom_source_code)

    num_calldataloads = 0
    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                # transform `param` instructions into "symbolic" values for
                # hevm via calldataload
                if inst.opcode == "param":
                    # hevm limit: 256 bytes of symbolic calldata
                    assert num_calldataloads < 8

                    inst.opcode = "calldataload"
                    inst.operands = [IRLiteral(num_calldataloads * 32)]
                    num_calldataloads += 1

            term = bb.instructions[-1]
            # test convention, terminate by `return`ing the variables
            # you want to check
            assert term.opcode == "sink"
            num_return_values = 0
            for op in term.operands:
                ptr = IRLiteral(num_return_values * 32)
                new_inst = IRInstruction("mstore", [op, ptr])
                bb.insert_instruction(new_inst, index=-1)
                num_return_values += 1

            # return 0, 32 * num_variables
            term.operands = [IRLiteral(num_return_values * 32), IRLiteral(0)]

        ac = IRAnalysesCache(fn)
        # requirement for venom_to_assembly
        StoreExpansionPass(ac, fn).run_pass()

    compiler = VenomCompiler([ctx])
    return assembly_to_evm(compiler.generate_evm(no_optimize=True))[0].hex()


def hevm_check_venom(pre, post, verbose=False):
    global HAS_HEVM

    if not HAS_HEVM:
        return

    # perform hevm equivalence check
    if verbose:
        print("HEVM COMPARE.")
        print("BEFORE:", pre)
        print("OPTIMIZED:", post)
    bytecode1 = _prep_hevm_venom(pre)
    bytecode2 = _prep_hevm_venom(post)

    hevm_check_bytecode(bytecode1, bytecode2, verbose=verbose)


def hevm_check_bytecode(bytecode1, bytecode2, verbose=False):
    # debug:
    if verbose:
        print("RUN HEVM:")
        print(bytecode1)
        print(bytecode2)

    subp_args = ["hevm", "equivalence", "--code-a", bytecode1, "--code-b", bytecode2]

    if verbose:
        subprocess.check_call(subp_args)
    else:
        subprocess.check_output(subp_args)
