from collections import OrderedDict
from typing import Any, Callable, Optional, Sequence, Union

from vyper.compiler import output
from vyper.compiler.phases import CompilerData
from vyper.evm.opcodes import DEFAULT_EVM_VERSION, evm_wrapper
from vyper.typing import (
    ContractCodes,
    InterfaceDict,
    InterfaceImports,
    OutputDict,
    OutputFormats,
)

OUTPUT_FORMATS = {
    # requires vyper_module
    "ast_dict": output.build_ast_dict,
    "layout": output.build_layout_output,
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
    use_ovm: bool = False,
) -> OrderedDict:
    """
    Generate compiler output(s) from one or more contract source codes.

    Arguments
    ---------
    contract_sources: Dict[str, str]
        Vyper source codes to be compiled. Formatted as `{"contract name": "source code"}`
    output_formats: List, optional
        List of compiler outputs to generate. Possible options are all the keys
        in `OUTPUT_FORMATS`. If not given, the deployment bytecode is generated.
    exc_handler: Callable, optional
        Callable used to handle exceptions if the compilation fails. Should accept
        two arguments - the name of the contract, and the exception that was raised
    initial_id: int, optional
        The lowest source ID value to be used when generating the source map.
    evm_version: str, optional
        The target EVM ruleset to compile for. If not given, defaults to the latest
        implemented ruleset.
    use_ovm: bool, optional
        Whether or not to use the OVM backend. Defaults to False
    interface_codes: Dict, optional
        Interfaces that may be imported by the contracts during compilation.

        * May be a singular dictionary shared across all sources to be compiled,
          i.e. `{'interface name': "definition"}`
        * or may be organized according to contracts that are being compiled, i.e.
          `{'contract name': {'interface name': "definition"}`

        * Interface definitions are formatted as: `{'type': "json/vyper", 'code': "interface code"}`
        * JSON interfaces are given as lists, vyper interfaces as strings

    Returns
    -------
    Dict
        Compiler output as `{'contract name': {'output key': "output data"}}`
    """

    if output_formats is None:
        output_formats = ("bytecode",)
    if isinstance(output_formats, Sequence):
        output_formats = dict((k, output_formats) for k in contract_sources.keys())

    out: OrderedDict = OrderedDict()
    for source_id, contract_name in enumerate(sorted(contract_sources), start=initial_id):
        source_code = contract_sources[contract_name]
        interfaces: Any = interface_codes
        if (
            isinstance(interfaces, dict)
            and contract_name in interfaces
            and isinstance(interfaces[contract_name], dict)
        ):
            interfaces = interfaces[contract_name]

        compiler_data = CompilerData(source_code, contract_name, interfaces, source_id, use_ovm)
        for output_format in output_formats[contract_name]:
            if output_format not in OUTPUT_FORMATS:
                raise ValueError(f"Unsupported format type {repr(output_format)}")
            try:
                out.setdefault(contract_name, {})
                out[contract_name][output_format] = OUTPUT_FORMATS[output_format](compiler_data)
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(contract_name, exc)
                else:
                    raise exc

    return out


UNKNOWN_CONTRACT_NAME = "<unknown>"


def compile_code(
    contract_source: str,
    output_formats: Optional[OutputFormats] = None,
    interface_codes: Optional[InterfaceImports] = None,
    evm_version: str = DEFAULT_EVM_VERSION,
    use_ovm: bool = False,
) -> dict:
    """
    Generate compiler output(s) from a single contract source code.

    Arguments
    ---------
    contract_source: str
        Vyper source codes to be compiled.
    output_formats: List, optional
        List of compiler outputs to generate. Possible options are all the keys
        in `OUTPUT_FORMATS`. If not given, the deployment bytecode is generated.
    evm_version: str, optional
        The target EVM ruleset to compile for. If not given, defaults to the latest
        implemented ruleset.
    interface_codes: Dict, optional
        Interfaces that may be imported by the contracts during compilation.

        * Formatted as as `{'interface name': {'type': "json/vyper", 'code': "interface code"}}`
        * JSON interfaces are given as lists, vyper interfaces as strings

    Returns
    -------
    Dict
        Compiler output as `{'output key': "output data"}`
    """

    contract_sources = {UNKNOWN_CONTRACT_NAME: contract_source}

    return compile_codes(
        contract_sources,
        output_formats,
        interface_codes=interface_codes,
        evm_version=evm_version,
        use_ovm=use_ovm,
    )[UNKNOWN_CONTRACT_NAME]
