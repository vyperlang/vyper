import base64
import warnings
from collections import deque
from pathlib import PurePath

from vyper.ast import ast_to_dict
from vyper.codegen.ir_node import IRnode
from vyper.compiler.output_bundle import SolcJSONWriter, VyperArchiveWriter
from vyper.compiler.phases import CompilerData
from vyper.compiler.utils import build_gas_estimates
from vyper.evm import opcodes
from vyper.exceptions import VyperException
from vyper.ir import compile_ir
from vyper.semantics.types.function import FunctionVisibility, StateMutability
from vyper.typing import StorageLayout
from vyper.utils import vyper_warn
from vyper.warnings import ContractSizeLimitWarning


def build_ast_dict(compiler_data: CompilerData) -> dict:
    ast_dict = {
        "contract_name": str(compiler_data.contract_path),
        "ast": ast_to_dict(compiler_data.vyper_module),
    }
    return ast_dict


def build_annotated_ast_dict(compiler_data: CompilerData) -> dict:
    annotated_ast_dict = {
        "contract_name": str(compiler_data.contract_path),
        "ast": ast_to_dict(compiler_data.annotated_vyper_module),
    }
    return annotated_ast_dict


def build_devdoc(compiler_data: CompilerData) -> dict:
    return compiler_data.natspec.devdoc


def build_userdoc(compiler_data: CompilerData) -> dict:
    return compiler_data.natspec.userdoc


def build_solc_json(compiler_data: CompilerData) -> str:
    # request bytecode to ensure the input compiles through all the
    # compilation passes, emit warnings if there are any issues
    # (this allows use cases like sending a bug reproduction while
    # still alerting the user in the common case that they didn't
    # mean to have a bug)
    try:
        _ = compiler_data.bytecode
    except VyperException as e:
        vyper_warn(
            f"Exceptions encountered during code generation (but producing output anyway): {e}"
        )
    writer = SolcJSONWriter(compiler_data)
    writer.write()
    return writer.output()


def build_archive(compiler_data: CompilerData) -> bytes:
    # ditto
    try:
        _ = compiler_data.bytecode
    except VyperException as e:
        vyper_warn(
            f"Exceptions encountered during code generation (but producing archive anyway): {e}"
        )
    writer = VyperArchiveWriter(compiler_data)
    writer.write()
    return writer.output()


def build_archive_b64(compiler_data: CompilerData) -> str:
    return base64.b64encode(build_archive(compiler_data)).decode("ascii")


def build_integrity(compiler_data: CompilerData) -> str:
    return compiler_data.compilation_target._metadata["type"].integrity_sum


def build_external_interface_output(compiler_data: CompilerData) -> str:
    interface = compiler_data.annotated_vyper_module._metadata["type"].interface
    stem = PurePath(compiler_data.contract_path).stem
    # capitalize words separated by '_'
    # ex: test_interface.vy -> TestInterface
    name = "".join([x.capitalize() for x in stem.split("_")])
    out = f"\n# External Interfaces\ninterface {name}:\n"

    for func in interface.functions.values():
        if func.visibility == FunctionVisibility.INTERNAL or func.name == "__init__":
            continue
        args = ", ".join([f"{arg.name}: {arg.typ}" for arg in func.arguments])
        return_value = f" -> {func.return_type}" if func.return_type is not None else ""
        mutability = func.mutability.value
        out = f"{out}    def {func.name}({args}){return_value}: {mutability}\n"

    return out


def build_interface_output(compiler_data: CompilerData) -> str:
    interface = compiler_data.annotated_vyper_module._metadata["type"].interface
    out = ""

    if interface.events:
        out = "# Events\n\n"
        for event in interface.events.values():
            encoded_args = "\n    ".join(f"{name}: {typ}" for name, typ in event.arguments.items())
            out = f"{out}event {event.name}:\n    {encoded_args if event.arguments else 'pass'}\n"

    if interface.functions:
        out = f"{out}\n# Functions\n\n"
        for func in interface.functions.values():
            if func.visibility == FunctionVisibility.INTERNAL or func.name == "__init__":
                continue
            if func.mutability != StateMutability.NONPAYABLE:
                out = f"{out}@{func.mutability.value}\n"
            args = ", ".join([f"{arg.name}: {arg.typ}" for arg in func.arguments])
            return_value = f" -> {func.return_type}" if func.return_type is not None else ""
            out = f"{out}@external\ndef {func.name}({args}){return_value}:\n    ...\n\n"

    return out


def build_bb_output(compiler_data: CompilerData) -> IRnode:
    return compiler_data.venom_functions[0]


def build_bb_runtime_output(compiler_data: CompilerData) -> IRnode:
    return compiler_data.venom_functions[1]


def build_cfg_output(compiler_data: CompilerData) -> str:
    return compiler_data.venom_functions[0].as_graph()


def build_cfg_runtime_output(compiler_data: CompilerData) -> str:
    return compiler_data.venom_functions[1].as_graph()


def build_ir_output(compiler_data: CompilerData) -> IRnode:
    if compiler_data.show_gas_estimates:
        IRnode.repr_show_gas = True
    return compiler_data.ir_nodes


def build_ir_runtime_output(compiler_data: CompilerData) -> IRnode:
    if compiler_data.show_gas_estimates:
        IRnode.repr_show_gas = True
    return compiler_data.ir_runtime


def _ir_to_dict(ir_node):
    # Currently only supported with IRnode and not VenomIR
    if not isinstance(ir_node, IRnode):
        return
    args = ir_node.args
    if len(args) > 0 or ir_node.value == "seq":
        return {ir_node.value: [_ir_to_dict(x) for x in args]}
    return ir_node.value


def build_ir_dict_output(compiler_data: CompilerData) -> dict:
    return _ir_to_dict(compiler_data.ir_nodes)


def build_ir_runtime_dict_output(compiler_data: CompilerData) -> dict:
    return _ir_to_dict(compiler_data.ir_runtime)


def build_metadata_output(compiler_data: CompilerData) -> dict:
    sigs = compiler_data.function_signatures

    def _var_rec_dict(variable_record):
        ret = vars(variable_record).copy()
        ret["typ"] = str(ret["typ"])
        if ret["data_offset"] is None:
            del ret["data_offset"]
        for k in ("blockscopes", "defined_at", "encoding"):
            del ret[k]
        ret["location"] = ret["location"].name
        return ret

    def _to_dict(func_t):
        ret = vars(func_t).copy()
        ret["return_type"] = str(ret["return_type"])
        ret["_ir_identifier"] = func_t._ir_info.ir_identifier

        for attr in ("mutability", "visibility"):
            ret[attr] = ret[attr].name.lower()

        # e.g. {"x": vy_ast.Int(..)} -> {"x": 1}
        ret["default_values"] = {
            k: val.node_source_code for k, val in func_t.default_values.items()
        }

        for attr in ("positional_args", "keyword_args"):
            args = ret[attr]
            ret[attr] = {arg.name: str(arg.typ) for arg in args}

        ret["frame_info"] = vars(func_t._ir_info.frame_info).copy()
        del ret["frame_info"]["frame_vars"]  # frame_var.pos might be IR, cannot serialize

        keep_keys = {
            "name",
            "return_type",
            "positional_args",
            "keyword_args",
            "default_values",
            "frame_info",
            "mutability",
            "visibility",
            "_ir_identifier",
            "nonreentrant_key",
        }
        ret = {k: v for k, v in ret.items() if k in keep_keys}
        return ret

    return {"function_info": {name: _to_dict(sig) for (name, sig) in sigs.items()}}


def build_method_identifiers_output(compiler_data: CompilerData) -> dict:
    module_t = compiler_data.annotated_vyper_module._metadata["type"]
    functions = module_t.exposed_functions

    return {k: hex(v) for fn_t in functions for k, v in fn_t.method_ids.items()}


def build_abi_output(compiler_data: CompilerData) -> list:
    module_t = compiler_data.annotated_vyper_module._metadata["type"]
    _ = compiler_data.ir_runtime  # ensure _ir_info is generated

    abi = module_t.interface.to_toplevel_abi_dict()
    if compiler_data.show_gas_estimates:
        # Add gas estimates for each function to ABI
        gas_estimates = build_gas_estimates(compiler_data.function_signatures)
        for func in abi:
            try:
                func_signature = func["name"]
            except KeyError:
                # constructor and fallback functions don't have a name
                continue

            func_name, _, _ = func_signature.partition("(")
            # This check ensures we skip __init__ since it has no estimate
            if func_name in gas_estimates:
                func["gas"] = gas_estimates[func_name]
    return abi


def build_asm_output(compiler_data: CompilerData) -> str:
    return _build_asm(compiler_data.assembly)


def build_layout_output(compiler_data: CompilerData) -> StorageLayout:
    # in the future this might return (non-storage) layout,
    # for now only storage layout is returned.
    return compiler_data.storage_layout


def _build_asm(asm_list):
    output_string = ""
    in_push = 0
    for node in asm_list:
        if isinstance(node, list):
            output_string += "{ " + _build_asm(node) + "} "
            continue

        if in_push > 0:
            assert isinstance(node, int), node
            output_string += hex(node)[2:].rjust(2, "0")
            if in_push == 1:
                output_string += " "
            in_push -= 1
        else:
            output_string += str(node) + " "

            if isinstance(node, str) and node.startswith("PUSH") and node != "PUSH0":
                assert in_push == 0
                in_push = int(node[4:])
                output_string += "0x"

    return output_string


def _build_node_identifier(ast_node):
    assert ast_node.module_node is not None, type(ast_node)
    return (ast_node.module_node.source_id, ast_node.node_id)


def _build_source_map_output(compiler_data, bytecode, pc_maps):
    """
    Generate source map output in various formats. Note that integrations
    are encouraged to use pc_ast_map since the information it provides is
    a superset of the other formats, and the other types are included
    for legacy reasons.
    """
    # sort the pc maps alphabetically
    # CMC 2024-03-09 is this really necessary?
    out = {}
    for k in sorted(pc_maps.keys()):
        out[k] = pc_maps[k]

    ast_map = out.pop("pc_raw_ast_map")

    assert isinstance(ast_map, dict)  # lint
    if 0 not in ast_map:
        # tag it with source id
        ast_map[0] = compiler_data.annotated_vyper_module

    pc_pos_map = {k: compile_ir.getpos(v) for (k, v) in ast_map.items()}
    node_id_map = {k: _build_node_identifier(v) for (k, v) in ast_map.items()}
    compressed_map = _compress_source_map(ast_map, out["pc_jump_map"], len(bytecode))
    out["pc_pos_map_compressed"] = compressed_map
    out["pc_pos_map"] = pc_pos_map
    out["pc_ast_map"] = node_id_map
    # hint to consumers what the fields in pc_ast_map mean
    out["pc_ast_map_item_keys"] = ("source_id", "node_id")
    return out


def build_source_map_output(compiler_data: CompilerData) -> dict:
    bytecode, pc_maps = compile_ir.assembly_to_evm(
        compiler_data.assembly, insert_compiler_metadata=False
    )
    return _build_source_map_output(compiler_data, bytecode, pc_maps)


def build_source_map_runtime_output(compiler_data: CompilerData) -> dict:
    bytecode, pc_maps = compile_ir.assembly_to_evm(
        compiler_data.assembly_runtime, insert_compiler_metadata=False
    )
    return _build_source_map_output(compiler_data, bytecode, pc_maps)


# generate a solidity-style source map. this functionality is deprecated
# in favor of pc_ast_map, and may not be maintained to the same level
# as pc_ast_map.
def _compress_source_map(ast_map, jump_map, bytecode_size):
    ret = []

    jump_map = jump_map.copy()
    ast_map = ast_map.copy()

    for pc in range(bytecode_size):
        if pc in ast_map:
            ast_node = ast_map.pop(pc)
            # ast_node.src conveniently has the current position in
            # the correct, compressed format
            current_pos = [ast_node.src]
        else:
            current_pos = ["-1:-1:-1"]

        if pc in jump_map:
            jump_type = jump_map.pop(pc)
            current_pos.append(jump_type)

        ret.append(":".join(str(i) for i in current_pos))

    assert len(ast_map) == 0, ast_map
    assert len(jump_map) == 0, jump_map

    return ";".join(ret)


def build_bytecode_output(compiler_data: CompilerData) -> str:
    return f"0x{compiler_data.bytecode.hex()}"


def build_blueprint_bytecode_output(compiler_data: CompilerData) -> str:
    return f"0x{compiler_data.blueprint_bytecode.hex()}"


# EIP-170. Ref: https://eips.ethereum.org/EIPS/eip-170
EIP170_CONTRACT_SIZE_LIMIT: int = 2**14 + 2**13


def build_bytecode_runtime_output(compiler_data: CompilerData) -> str:
    compiled_bytecode_runtime_length = len(compiler_data.bytecode_runtime)
    if compiled_bytecode_runtime_length > EIP170_CONTRACT_SIZE_LIMIT:
        warnings.warn(
            f"Length of compiled bytecode is bigger than Ethereum contract size limit "
            "(see EIP-170: https://eips.ethereum.org/EIPS/eip-170): "
            f"{compiled_bytecode_runtime_length}b > {EIP170_CONTRACT_SIZE_LIMIT}b",
            ContractSizeLimitWarning,
            stacklevel=2,
        )
    return f"0x{compiler_data.bytecode_runtime.hex()}"


def build_opcodes_output(compiler_data: CompilerData) -> str:
    return _build_opcodes(compiler_data.bytecode)


def build_opcodes_runtime_output(compiler_data: CompilerData) -> str:
    return _build_opcodes(compiler_data.bytecode_runtime)


def _build_opcodes(bytecode: bytes) -> str:
    bytecode_sequence = deque(bytecode)

    opcode_map = dict((v[0], k) for k, v in opcodes.get_opcodes().items())
    opcode_output = []

    while bytecode_sequence:
        op = bytecode_sequence.popleft()
        opcode_output.append(opcode_map.get(op, f"VERBATIM_{hex(op)}"))
        if "PUSH" in opcode_output[-1] and opcode_output[-1] != "PUSH0":
            push_len = int(opcode_map[op][4:])
            # we can have push_len > len(bytecode_sequence) when there is data
            # (instead of code) at end of contract
            # CMC 2023-07-13 maybe just strip known data segments?
            push_len = min(push_len, len(bytecode_sequence))
            push_values = [f"{bytecode_sequence.popleft():0>2X}" for i in range(push_len)]
            opcode_output.append(f"0x{''.join(push_values)}")

    return " ".join(opcode_output)
