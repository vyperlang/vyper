from collections import (
    OrderedDict,
)
from typing import (
    Any,
    Callable,
    Sequence,
    Union,
)

from vyper.compiler import (
    output,
)
from vyper.compiler.data import (
    CompilerData,
)
from vyper.opcodes import (
    DEFAULT_EVM_VERSION,
    evm_wrapper,
)
from vyper.typing import (
    ContractCodes,
    InterfaceDict,
    InterfaceImports,
    OutputDict,
    OutputFormats,
)

OUTPUT_FORMATS = {
    # requires vyper_ast
    "ast_dict": output.build_ast_dict,
    # requires global_ctx
    "devdoc": output.build_devdoc,
    "userdoc": output.build_userdoc,
    # requires lll_node
    "external_interface": output.build_external_interface_output,
    "interface": output.build_interface_output,
    "ir": output.build_ir_output,
    "method_identifiers": output.build_method_identifiers_output,
    # requires assembly
    "abi": output.build_abi_output,
    "asm": output.build_asm_output,
    "source_map": output.build_source_map_output,
    # requires bytecode
    "bytecode": output.build_bytecode_output,
    "bytecode_runtime": output.build_bytecode_runtime_output,
    "opcodes": output.build_opcodes_output,
    "opcodes_runtime": output.build_opcodes_runtime_output,
}


@evm_wrapper
def compile_codes(
    contract_sources: ContractCodes,
    output_formats: Union[OutputDict, OutputFormats, None] = None,
    exc_handler: Union[Callable, None] = None,
    interface_codes: Union[InterfaceDict, InterfaceImports, None] = None,
    initial_id: int = 0,
) -> OrderedDict:

    if output_formats is None:
        output_formats = ("bytecode",)
    if isinstance(output_formats, Sequence):
        output_formats = dict((k, output_formats) for k in contract_sources.keys())

    out: OrderedDict = OrderedDict()
    for source_id, contract_name in enumerate(
        sorted(contract_sources), start=initial_id
    ):
        # trailing newline fixes python parsing bug when source ends in a comment
        # https://bugs.python.org/issue35107
        source_code = f"{contract_sources[contract_name]}\n"
        interfaces: Any = interface_codes
        if (
            isinstance(interfaces, dict)
            and contract_name in interfaces
            and isinstance(interfaces[contract_name], dict)
        ):
            interfaces = interfaces[contract_name]

        compiler_data = CompilerData(contract_name, source_code, interfaces, source_id)
        for output_format in output_formats[contract_name]:
            if output_format not in OUTPUT_FORMATS:
                raise ValueError(f"Unsupported format type {repr(output_format)}")
            try:
                out.setdefault(contract_name, {})
                out[contract_name][output_format] = OUTPUT_FORMATS[output_format](
                    compiler_data
                )
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    return out


UNKNOWN_CONTRACT_NAME = "<unknown>"


def compile_code(
    code, output_formats=None, interface_codes=None, evm_version=DEFAULT_EVM_VERSION
):

    contract_sources = {UNKNOWN_CONTRACT_NAME: code}

    return compile_codes(
        contract_sources,
        output_formats,
        interface_codes=interface_codes,
        evm_version=evm_version,
    )[UNKNOWN_CONTRACT_NAME]
