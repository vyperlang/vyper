import warnings
from collections import OrderedDict, deque
from pathlib import Path

import asttokens

from vyper.ast import ast_to_dict, parse_natspec
from vyper.codegen.ir_node import IRnode
from vyper.compiler.phases import CompilerData
from vyper.compiler.utils import build_gas_estimates
from vyper.evm import opcodes
from vyper.ir import compile_ir
from vyper.semantics.types.function import FunctionVisibility, StateMutability
from vyper.typing import StorageLayout
from vyper.warnings import ContractSizeLimitWarning


def build_ast_dict(compiler_data: CompilerData) -> dict:
    ast_dict = {
        "contract_name": compiler_data.contract_name,
        "ast": ast_to_dict(compiler_data.vyper_module),
    }
    return ast_dict


def build_devdoc(compiler_data: CompilerData) -> dict:
    userdoc, devdoc = parse_natspec(compiler_data.vyper_module_folded)
    return devdoc


def build_userdoc(compiler_data: CompilerData) -> dict:
    userdoc, devdoc = parse_natspec(compiler_data.vyper_module_folded)
    return userdoc


def build_external_interface_output(compiler_data: CompilerData) -> str:
    interface = compiler_data.vyper_module_folded._metadata["type"]
    stem = Path(compiler_data.contract_name).stem
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
    interface = compiler_data.vyper_module_folded._metadata["type"]
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
            out = f"{out}@external\ndef {func.name}({args}){return_value}:\n    pass\n\n"

    return out


def build_ir_output(compiler_data: CompilerData) -> IRnode:
    if compiler_data.show_gas_estimates:
        IRnode.repr_show_gas = True
    return compiler_data.ir_nodes


def build_ir_runtime_output(compiler_data: CompilerData) -> IRnode:
    if compiler_data.show_gas_estimates:
        IRnode.repr_show_gas = True
    return compiler_data.ir_runtime


def _ir_to_dict(ir_node):
    args = ir_node.args
    if len(args) > 0 or ir_node.value == "seq":
        return {ir_node.value: [_ir_to_dict(x) for x in args]}
    return ir_node.value


def build_ir_dict_output(compiler_data: CompilerData) -> dict:
    return _ir_to_dict(compiler_data.ir_nodes)


def build_ir_runtime_dict_output(compiler_data: CompilerData) -> dict:
    return _ir_to_dict(compiler_data.ir_runtime)


def build_metadata_output(compiler_data: CompilerData) -> dict:
    warnings.warn("metadata output format is unstable!")
    sigs = compiler_data.function_signatures

    def _var_rec_dict(variable_record):
        ret = vars(variable_record)
        ret["typ"] = str(ret["typ"])
        if ret["data_offset"] is None:
            del ret["data_offset"]
        for k in ("blockscopes", "defined_at", "encoding"):
            del ret[k]
        ret["location"] = ret["location"].name
        return ret

    def _to_dict(func_t):
        ret = vars(func_t)
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

        ret["frame_info"] = vars(func_t._ir_info.frame_info)
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
    interface = compiler_data.vyper_module_folded._metadata["type"]
    functions = interface.functions.values()

    return {k: hex(v) for func in functions for k, v in func.method_ids.items()}


def build_abi_output(compiler_data: CompilerData) -> list:
    abi = compiler_data.vyper_module_folded._metadata["type"].to_toplevel_abi_dict()
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


def build_source_map_output(compiler_data: CompilerData) -> OrderedDict:
    _, line_number_map = compile_ir.assembly_to_evm(
        compiler_data.assembly_runtime,
        insert_vyper_signature=True,
        disable_bytecode_metadata=compiler_data.no_bytecode_metadata,
    )
    # Sort line_number_map
    out = OrderedDict()
    for k in sorted(line_number_map.keys()):
        out[k] = line_number_map[k]

    out["pc_pos_map_compressed"] = _compress_source_map(
        compiler_data.source_code, out["pc_pos_map"], out["pc_jump_map"], compiler_data.source_id
    )
    out["pc_pos_map"] = dict((k, v) for k, v in out["pc_pos_map"].items() if v)
    return out


def _compress_source_map(code, pos_map, jump_map, source_id):
    linenos = asttokens.LineNumbers(code)
    ret = [f"-1:-1:{source_id}:-"]
    last_pos = [-1, -1, source_id]

    for pc in sorted(pos_map)[1:]:
        current_pos = [-1, -1, source_id]
        if pos_map[pc]:
            current_pos[0] = linenos.line_to_offset(*pos_map[pc][:2])
            current_pos[1] = linenos.line_to_offset(*pos_map[pc][2:]) - current_pos[0]

        if pc in jump_map:
            current_pos.append(jump_map[pc])

        for i in range(2, -1, -1):
            if current_pos[i] != last_pos[i]:
                last_pos[i] = current_pos[i]
            elif len(current_pos) == i + 1:
                current_pos.pop()
            else:
                current_pos[i] = ""

        ret.append(":".join(str(i) for i in current_pos))

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
        opcode_output.append(opcode_map[op])
        if "PUSH" in opcode_output[-1] and opcode_output[-1] != "PUSH0":
            push_len = int(opcode_map[op][4:])
            push_values = [hex(bytecode_sequence.popleft())[2:] for i in range(push_len)]
            opcode_output.append(f"0x{''.join(push_values).upper()}")

    return " ".join(opcode_output)
