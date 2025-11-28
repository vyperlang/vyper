import base64
from collections import deque
from pathlib import PurePath
from typing import Iterable

import vyper.ast as vy_ast
from vyper.ast.utils import ast_to_dict
from vyper.codegen.ir_node import IRnode
from vyper.compiler.output_bundle import SolcJSONWriter, VyperArchiveWriter
from vyper.compiler.phases import CompilerData
from vyper.compiler.utils import build_gas_estimates
from vyper.evm import opcodes
from vyper.evm.assembler.symbols import resolve_symbols
from vyper.exceptions import VyperException
from vyper.ir import compile_ir
from vyper.semantics.types.function import ContractFunctionT, FunctionVisibility, StateMutability
from vyper.typing import StorageLayout
from vyper.utils import safe_relpath
from vyper.venom.ir_node_to_venom import _pass_via_stack, _returns_word
from vyper.warnings import ContractSizeLimit, vyper_warn


def build_ast_dict(compiler_data: CompilerData) -> dict:
    ast_dict = {
        "contract_name": str(compiler_data.contract_path),
        "ast": ast_to_dict(compiler_data.vyper_module),
    }
    return ast_dict


def _get_reachable_imports(compiler_data: CompilerData) -> Iterable[vy_ast.Module]:
    import_analysis = compiler_data.resolved_imports

    # get all reachable imports including recursion
    # (NOTE: does not include imported json interfaces.)
    imported_modules = list(import_analysis.compiler_inputs.values())
    imported_modules = [mod for mod in imported_modules if isinstance(mod, vy_ast.Module)]
    if import_analysis.toplevel_module in imported_modules:
        # this shouldn't actually happen, but remove in case our
        # assumption is violated in the future
        imported_modules.remove(import_analysis.toplevel_module)

    return imported_modules


def build_annotated_ast_dict(compiler_data: CompilerData) -> dict:
    imported_modules = _get_reachable_imports(compiler_data)
    annotated_ast_dict = {
        "contract_name": str(compiler_data.contract_path),
        "ast": ast_to_dict(compiler_data.annotated_vyper_module),
        "imports": [ast_to_dict(ast) for ast in imported_modules],
    }
    return annotated_ast_dict


def build_devdoc(compiler_data: CompilerData) -> dict:
    return compiler_data.natspec.devdoc


def build_userdoc(compiler_data: CompilerData) -> dict:
    return compiler_data.natspec.userdoc


def _request_bytecode_for_bundle(compiler_data: CompilerData, pretty_output_type: str) -> None:
    """
    request bytecode to ensure the input compiles through all the
    compilation passes, emit warnings if there are any issues
    (this allows use cases like sending a bug reproduction while
    still alerting the user in the common case that they didn't
    mean to have a bug). called for its side effects.

    params:
        compiler_data: CompilerData
        pretty_output_type: str, human readable type of the output
    """
    # must be able to parse + resolve imports
    _ = compiler_data.resolved_imports
    try:
        _ = compiler_data.bytecode
    except VyperException as e:
        msg = "Exceptions encountered during code generation"
        msg += f" (but producing {pretty_output_type} anyway): {e}"
        vyper_warn(msg)


def build_solc_json(compiler_data: CompilerData) -> str:
    _request_bytecode_for_bundle(compiler_data, pretty_output_type="output")
    writer = SolcJSONWriter(compiler_data)
    writer.write()
    return writer.output()


def build_archive(compiler_data: CompilerData) -> bytes:
    _request_bytecode_for_bundle(compiler_data, pretty_output_type="archive")
    writer = VyperArchiveWriter(compiler_data)
    writer.write()
    return writer.output()


def build_archive_b64(compiler_data: CompilerData) -> str:
    return base64.b64encode(build_archive(compiler_data)).decode("ascii")


def build_integrity(compiler_data: CompilerData) -> str:
    return compiler_data.integrity_sum


def build_external_interface_output(compiler_data: CompilerData) -> str:
    interface = compiler_data.annotated_vyper_module._metadata["type"].interface
    stem = PurePath(compiler_data.contract_path).stem

    name = stem.title().replace("_", "")
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

    if len(interface.structs) > 0:
        out += "# Structs\n\n"
        for struct in interface.structs.values():
            out += f"struct {struct.name}:\n"
            for member_name, member_type in struct.members.items():
                out += f"    {member_name}: {member_type}\n"
            out += "\n\n"

    if len(interface.flags) > 0:
        out += "# Flags\n\n"
        for flag in interface.flags.values():
            out += f"flag {flag.name}:\n"
            for flag_value in flag._flag_members:
                out += f"    {flag_value}\n"
            out += "\n\n"

    if len(interface.events) > 0:
        out += "# Events\n\n"
        for event in interface.events.values():
            encoded_args = "\n    ".join(f"{name}: {typ}" for name, typ in event.arguments.items())
            out += f"event {event.name}:\n    {encoded_args if event.arguments else 'pass'}\n\n\n"

    if len(interface.functions) > 0:
        out += "# Functions\n\n"
        for func in interface.functions.values():
            if func.visibility == FunctionVisibility.INTERNAL or func.name == "__init__":
                continue
            if func.mutability != StateMutability.NONPAYABLE:
                out += f"@{func.mutability.value}\n"
            args = ", ".join([f"{arg.name}: {arg.typ}" for arg in func.arguments])
            return_value = f" -> {func.return_type}" if func.return_type is not None else ""
            out += f"@external\ndef {func.name}({args}){return_value}:\n    ...\n\n\n"

    out = out.rstrip("\n")
    out += "\n"

    return out


def build_bb_output(compiler_data: CompilerData) -> IRnode:
    return compiler_data.venom_deploytime


def build_bb_runtime_output(compiler_data: CompilerData) -> IRnode:
    return compiler_data.venom_runtime


def build_cfg_output(compiler_data: CompilerData) -> str:
    return compiler_data.venom_deploytime.as_graph()


def build_cfg_runtime_output(compiler_data: CompilerData) -> str:
    return compiler_data.venom_runtime.as_graph()


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


def build_settings_output(compiler_data: CompilerData) -> dict:
    return compiler_data.settings.as_dict()


def build_metadata_output(compiler_data: CompilerData) -> dict:
    # need ir info to be computed
    _ = compiler_data.function_signatures
    module_t = compiler_data.annotated_vyper_module._metadata["type"]
    sigs = dict[str, ContractFunctionT]()

    def _fn_identifier(fn_t):
        fn_id = fn_t._function_id
        return f"{fn_t.name} ({fn_id})"

    exposed_fns = module_t.exposed_functions.copy()
    if module_t.init_function is not None:
        exposed_fns.append(module_t.init_function)

    for fn_t in exposed_fns:
        assert isinstance(fn_t.ast_def, vy_ast.FunctionDef)
        for rif_t in fn_t.reachable_internal_functions:
            k = _fn_identifier(rif_t)
            if k in sigs:
                # sanity check that keys are injective with functions
                assert sigs[k] == rif_t, (k, sigs[k], rif_t)
            sigs[k] = rif_t

        fn_id = _fn_identifier(fn_t)
        assert fn_id not in sigs
        sigs[fn_id] = fn_t

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

        ret["module_path"] = safe_relpath(func_t.decl_node.module_node.resolved_path)
        ret["source_id"] = func_t.decl_node.module_node.source_id
        ret["function_id"] = func_t._function_id

        if func_t.is_internal and compiler_data.settings.experimental_codegen:
            pass_via_stack = _pass_via_stack(func_t)
            pass_via_stack_list = [
                arg for (arg, is_stack_arg) in pass_via_stack.items() if is_stack_arg
            ]
            ret["venom_via_stack"] = pass_via_stack_list
            ret["venom_return_via_stack"] = _returns_word(func_t)

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
            "module_path",
            "source_id",
            "function_id",
            "venom_via_stack",
            "venom_return_via_stack",
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
    if not compiler_data.annotated_vyper_module.is_interface:
        _ = compiler_data.ir_runtime  # ensure _ir_info is generated

    abi = module_t.interface.to_toplevel_abi_dict()
    if module_t.init_function:
        abi += module_t.init_function.to_toplevel_abi_dict()

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


def build_asm_runtime_output(compiler_data: CompilerData) -> str:
    return _build_asm(compiler_data.assembly_runtime)


def build_layout_output(compiler_data: CompilerData) -> StorageLayout:
    # in the future this might return (non-storage) layout,
    # for now only storage layout is returned.
    return compiler_data.storage_layout


def _build_asm(asm_list):
    output_string = "__entry__:"
    in_push = 0
    for item in asm_list:
        if isinstance(item, (compile_ir.Label, compile_ir.DataHeader)):
            output_string += f"\n\n{item}:"
            continue

        if in_push > 0:
            assert isinstance(item, int), item
            output_string += hex(item)[2:].rjust(2, "0")
            in_push -= 1
        else:
            output_string += f"\n    {item}"

            if isinstance(item, str) and item.startswith("PUSH") and item != "PUSH0":
                assert in_push == 0
                in_push = int(item[4:])
                output_string += " 0x"

    return output_string


def _build_node_identifier(ast_node):
    assert ast_node.module_node is not None, type(ast_node)
    return (ast_node.module_node.source_id, ast_node.node_id)


def _getpos(node):
    return (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)


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

    pc_pos_map = {k: _getpos(v) for (k, v) in ast_map.items()}
    node_id_map = {k: _build_node_identifier(v) for (k, v) in ast_map.items()}
    compressed_map = _compress_source_map(ast_map, out["pc_jump_map"], len(bytecode))
    out["pc_pos_map_compressed"] = compressed_map
    out["pc_pos_map"] = pc_pos_map
    out["pc_ast_map"] = node_id_map
    # hint to consumers what the fields in pc_ast_map mean
    out["pc_ast_map_item_keys"] = ("source_id", "node_id")
    return out


def build_source_map_output(compiler_data: CompilerData) -> dict:
    bytecode = compiler_data.bytecode
    source_map = compiler_data.source_map
    return _build_source_map_output(compiler_data, bytecode, source_map)


def build_source_map_runtime_output(compiler_data: CompilerData) -> dict:
    bytecode = compiler_data.bytecode_runtime
    source_map = compiler_data.source_map_runtime
    return _build_source_map_output(compiler_data, bytecode, source_map)


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


def build_symbol_map(compiler_data: CompilerData) -> dict[str, int]:
    sym, _, _ = resolve_symbols(compiler_data.assembly)
    return {k.label: v for (k, v) in sym.items()}


def build_symbol_map_runtime(compiler_data: CompilerData) -> dict[str, int]:
    sym, _, _ = resolve_symbols(compiler_data.assembly_runtime)
    return {k.label: v for (k, v) in sym.items()}


def build_bytecode_output(compiler_data: CompilerData) -> str:
    return f"0x{compiler_data.bytecode.hex()}"


def build_blueprint_bytecode_output(compiler_data: CompilerData) -> str:
    return f"0x{compiler_data.blueprint_bytecode.hex()}"


# EIP-170. Ref: https://eips.ethereum.org/EIPS/eip-170
EIP170_CONTRACT_SIZE_LIMIT: int = 2**14 + 2**13


def build_bytecode_runtime_output(compiler_data: CompilerData) -> str:
    compiled_bytecode_runtime_length = len(compiler_data.bytecode_runtime)
    # NOTE: we should actually add the size of the immutables section to this.
    if compiled_bytecode_runtime_length > EIP170_CONTRACT_SIZE_LIMIT:
        vyper_warn(
            ContractSizeLimit(
                f"Length of compiled bytecode is bigger than Ethereum contract size limit "
                "(see EIP-170: https://eips.ethereum.org/EIPS/eip-170): "
                f"{compiled_bytecode_runtime_length}b > {EIP170_CONTRACT_SIZE_LIMIT}b"
            )
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
