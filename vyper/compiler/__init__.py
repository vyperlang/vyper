from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Union

import vyper.ast as vy_ast  # break an import cycle
import vyper.codegen.core as codegen
import vyper.compiler.output as output
from vyper.compiler.input_bundle import FileInput, InputBundle, PathLike
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings
from vyper.evm.opcodes import DEFAULT_EVM_VERSION, anchor_evm_version
from vyper.typing import ContractPath, OutputFormats, StorageLayout

OUTPUT_FORMATS = {
    # requires vyper_module
    "ast_dict": output.build_ast_dict,
    # requires annotated_vyper_module
    "annotated_ast_dict": output.build_annotated_ast_dict,
    "layout": output.build_layout_output,
    # requires global_ctx
    "devdoc": output.build_devdoc,
    "userdoc": output.build_userdoc,
    # requires ir_node
    "external_interface": output.build_external_interface_output,
    "interface": output.build_interface_output,
    "bb": output.build_bb_output,
    "bb_runtime": output.build_bb_runtime_output,
    "ir": output.build_ir_output,
    "ir_runtime": output.build_ir_runtime_output,
    "ir_dict": output.build_ir_dict_output,
    "ir_runtime_dict": output.build_ir_runtime_dict_output,
    "method_identifiers": output.build_method_identifiers_output,
    "metadata": output.build_metadata_output,
    # requires assembly
    "abi": output.build_abi_output,
    "asm": output.build_asm_output,
    "source_map": output.build_source_map_output,
    "source_map_full": output.build_source_map_output,
    # requires bytecode
    "bytecode": output.build_bytecode_output,
    "bytecode_runtime": output.build_bytecode_runtime_output,
    "blueprint_bytecode": output.build_blueprint_bytecode_output,
    "opcodes": output.build_opcodes_output,
    "opcodes_runtime": output.build_opcodes_runtime_output,
}


UNKNOWN_CONTRACT_NAME = "<unknown>"


def compile_from_file_input(
    file_input: FileInput,
    input_bundle: InputBundle = None,
    settings: Settings = None,
    output_formats: Optional[OutputFormats] = None,
    storage_layout_override: Optional[StorageLayout] = None,
    no_bytecode_metadata: bool = False,
    show_gas_estimates: bool = False,
    exc_handler: Optional[Callable] = None,
) -> dict:
    """
    Main entry point into the compiler.

    Generate consumable compiler output(s) from a single contract source code.
    Basically, a wrapper around CompilerData which munges the output
    data into the requested output formats.

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
    source_id: int, optional
        source_id to tag AST nodes with. -1 if not provided.
    settings: Settings, optional
        Compiler settings.
    show_gas_estimates: bool, optional
        Show gas estimates for abi and ir output modes
    exc_handler: Callable, optional
        Callable used to handle exceptions if the compilation fails. Should accept
        two arguments - the name of the contract, and the exception that was raised
    no_bytecode_metadata: bool, optional
        Do not add metadata to bytecode. Defaults to False
    experimental_codegen: bool
        Use experimental codegen. Defaults to False

    Returns
    -------
    Dict
        Compiler output as `{'output key': "output data"}`
    """

    settings = settings or Settings()

    if output_formats is None:
        output_formats = ("bytecode",)

    # make IR output the same between runs
    codegen.reset_names()

    # TODO: maybe at this point we might as well just pass a `FileInput`
    # directly to `CompilerData`.
    compiler_data = CompilerData(
        file_input,
        input_bundle,
        settings,
        storage_layout_override,
        show_gas_estimates,
        no_bytecode_metadata,
    )

    ret = {}
    with anchor_evm_version(compiler_data.settings.evm_version):
        for output_format in output_formats:
            if output_format not in OUTPUT_FORMATS:
                raise ValueError(f"Unsupported format type {repr(output_format)}")
            try:
                formatter = OUTPUT_FORMATS[output_format]
                ret[output_format] = formatter(compiler_data)
            except Exception as exc:
                if exc_handler is not None:
                    exc_handler(str(file_input.path), exc)
                else:
                    raise exc

    return ret


def compile_code(
    source_code: str,
    contract_path: str | PathLike = UNKNOWN_CONTRACT_NAME,
    source_id: int = -1,
    resolved_path: PathLike | None = None,
    *args,
    **kwargs,
):
    # this function could be renamed to compile_from_string
    """
    Do the same thing as compile_from_file_input but takes a string for source
    code. This was previously the main entry point into the compiler
    # (`compile_from_file_input()` is newer)
    """
    if isinstance(contract_path, str):
        contract_path = Path(contract_path)
    file_input = FileInput(
        source_id=source_id,
        source_code=source_code,
        path=contract_path,
        resolved_path=resolved_path or contract_path,  # type: ignore
    )
    return compile_from_file_input(file_input, *args, **kwargs)
