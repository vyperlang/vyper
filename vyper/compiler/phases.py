import copy
from functools import cached_property
from pathlib import Path, PurePath
from typing import Any, Optional

import vyper.codegen.core as codegen
from vyper import ast as vy_ast
from vyper.ast import natspec
from vyper.codegen import module
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FileInput, FilesystemInputBundle, InputBundle, JSONInput
from vyper.compiler.settings import (
    OptimizationLevel,
    Settings,
    anchor_settings,
    merge_settings,
    should_run_legacy_optimizer,
)
from vyper.ir import compile_ir, optimizer
from vyper.semantics import analyze_module, set_data_positions, validate_compilation_target
from vyper.semantics.analysis.data_positions import generate_layout_export
from vyper.semantics.analysis.imports import resolve_imports
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.typing import StorageLayout
from vyper.utils import ERC5202_PREFIX, sha256sum
from vyper.venom import generate_assembly_experimental, generate_venom
from vyper.warnings import VyperWarning, vyper_warn

DEFAULT_CONTRACT_PATH = PurePath("VyperContract.vy")


class CompilerData:
    """
    Object for fetching and storing compiler data for a Vyper contract.

    This object acts as a wrapper over the pure compiler functions, triggering
    compilation phases as needed and providing the data for use when generating
    the final compiler outputs.

    Attributes
    ----------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node
    annotated_vyper_module: vy_ast.Module
        Annotated+analysed Vyper AST
    global_ctx : ModuleT
        Sorted, contextualized representation of the Vyper AST
    ir_nodes : IRnode
        IR used to generate deployment bytecode
    ir_runtime : IRnode
        IR used to generate runtime bytecode
    assembly : list
        Assembly instructions for deployment bytecode
    assembly_runtime : list
        Assembly instructions for runtime bytecode
    bytecode : bytes
        Deployment bytecode
    bytecode_runtime : bytes
        Runtime bytecode
    """

    def __init__(
        self,
        file_input: FileInput | str,
        input_bundle: InputBundle = None,
        settings: Settings = None,
        integrity_sum: str = None,
        storage_layout: JSONInput = None,
        show_gas_estimates: bool = False,
        no_bytecode_metadata: bool = False,
    ) -> None:
        """
        Initialization method.

        Arguments
        ---------
        file_input: FileInput | str
            A FileInput or string representing the input to the compiler.
            FileInput is preferred, but `str` is accepted as a convenience
            method (and also for backwards compatibility reasons)
        settings: Settings
            Set optimization mode.
        show_gas_estimates: bool, optional
            Show gas estimates for abi and ir output modes
        no_bytecode_metadata: bool, optional
            Do not add metadata to bytecode. Defaults to False
        """

        if isinstance(file_input, str):
            file_input = FileInput(
                contents=file_input,
                source_id=-1,
                path=DEFAULT_CONTRACT_PATH,
                resolved_path=DEFAULT_CONTRACT_PATH,
            )
        self.file_input = file_input
        self.storage_layout_override = storage_layout
        self.show_gas_estimates = show_gas_estimates
        self.no_bytecode_metadata = no_bytecode_metadata
        self.original_settings = settings
        self.input_bundle = input_bundle or FilesystemInputBundle([Path(".")])
        self.expected_integrity_sum = integrity_sum

    @cached_property
    def source_code(self):
        return self.file_input.source_code

    @cached_property
    def source_id(self):
        return self.file_input.source_id

    @cached_property
    def contract_path(self):
        return self.file_input.path

    @cached_property
    def vyper_module(self):
        is_vyi = self.contract_path.suffix == ".vyi"

        ast = vy_ast.parse_to_ast(
            self.source_code,
            self.source_id,
            module_path=self.contract_path.as_posix(),
            resolved_path=self.file_input.resolved_path.as_posix(),
            is_interface=is_vyi,
        )

        return ast

    @cached_property
    def settings(self):
        settings = self.vyper_module.settings

        if self.original_settings:
            og_settings = self.original_settings
            settings = merge_settings(og_settings, settings)
            assert self.original_settings == og_settings  # be paranoid
        else:
            # merge with empty Settings(), doesn't do much but it does
            # remove the compiler version
            settings = merge_settings(Settings(), settings)

        if settings.optimize is None:
            settings.optimize = OptimizationLevel.default()

        if settings.experimental_codegen is None:
            settings.experimental_codegen = False

        return settings

    def _compute_integrity_sum(self, imports_integrity_sum: str) -> str:
        if self.storage_layout_override is not None:
            layout_sum = self.storage_layout_override.sha256sum
            return sha256sum(layout_sum + imports_integrity_sum)
        return imports_integrity_sum

    @cached_property
    def _resolve_imports(self):
        # deepcopy so as to not interfere with `-f ast` output
        vyper_module = copy.deepcopy(self.vyper_module)
        with self.input_bundle.search_path(Path(vyper_module.resolved_path).parent):
            imports = resolve_imports(vyper_module, self.input_bundle)

        # check integrity sum
        integrity_sum = self._compute_integrity_sum(imports._integrity_sum)

        expected = self.expected_integrity_sum
        if expected is not None and integrity_sum != expected:
            # warn for now. strict/relaxed mode was considered but it costs
            # interface and testing complexity to add another feature flag.
            vyper_warn(
                f"Mismatched integrity sum! Expected {expected}"
                f" but got {integrity_sum}."
                " (This likely indicates a corrupted archive)"
            )

        return vyper_module, imports, integrity_sum

    @cached_property
    def integrity_sum(self):
        return self._resolve_imports[2]

    @cached_property
    def resolved_imports(self):
        return self._resolve_imports[1]

    @cached_property
    def _annotate(self) -> tuple[natspec.NatspecOutput, vy_ast.Module]:
        module = self._resolve_imports[0]
        analyze_module(module)
        nspec = natspec.parse_natspec(module)
        return nspec, module

    @cached_property
    def natspec(self) -> natspec.NatspecOutput:
        return self._annotate[0]

    @cached_property
    def annotated_vyper_module(self) -> vy_ast.Module:
        return self._annotate[1]

    @cached_property
    def compilation_target(self):
        """
        Get the annotated AST, and additionally run the global checks
        required for a compilation target.
        """
        module_t = self.annotated_vyper_module._metadata["type"]

        validate_compilation_target(module_t)
        return self.annotated_vyper_module

    @cached_property
    def storage_layout(self) -> StorageLayout:
        module_ast = self.compilation_target
        storage_layout = None
        if self.storage_layout_override is not None:
            storage_layout = self.storage_layout_override.data
        set_data_positions(module_ast, storage_layout)

        return generate_layout_export(module_ast)

    @property
    def global_ctx(self) -> ModuleT:
        # ensure storage layout is computed
        _ = self.storage_layout
        # ensure natspec is computed
        _ = self.natspec
        return self.annotated_vyper_module._metadata["type"]

    @cached_property
    def _ir_output(self):
        # fetch both deployment and runtime IR
        return generate_ir_nodes(self.global_ctx, self.settings)

    @property
    def ir_nodes(self) -> IRnode:
        ir, ir_runtime = self._ir_output
        return ir

    @property
    def ir_runtime(self) -> IRnode:
        ir, ir_runtime = self._ir_output
        return ir_runtime

    @property
    def function_signatures(self) -> dict[str, ContractFunctionT]:
        # some metadata gets calculated during codegen, so
        # ensure codegen is run:
        _ = self._ir_output

        fs = self.annotated_vyper_module.get_children(vy_ast.FunctionDef)
        return {f.name: f._metadata["func_type"] for f in fs}

    @cached_property
    def venom_runtime(self):
        runtime_venom = generate_venom(self.ir_runtime, self.settings)
        return runtime_venom

    @cached_property
    def venom_deploytime(self):
        data_sections = {"runtime_begin": self.bytecode_runtime}
        if self.bytecode_metadata is not None:
            data_sections["cbor_metadata"] = self.bytecode_metadata

        constants = {
            "runtime_codesize": len(self.bytecode_runtime),
            "immutables_len": self.compilation_target._metadata["type"].immutable_section_bytes,
        }

        venom_ctx = generate_venom(
            self.ir_nodes, self.settings, constants=constants, data_sections=data_sections
        )
        return venom_ctx

    @cached_property
    def assembly(self) -> list:
        metadata = None
        if not self.no_bytecode_metadata:
            metadata = bytes.fromhex(self.integrity_sum)

        if self.settings.experimental_codegen:
            assert self.settings.optimize is not None  # mypy hint
            return generate_assembly_experimental(
                self.venom_deploytime, optimize=self.settings.optimize
            )
        else:
            return generate_assembly(
                self.ir_nodes, self.settings.optimize, compiler_metadata=metadata
            )

    @cached_property
    def bytecode_metadata(self) -> Optional[bytes]:
        if self.no_bytecode_metadata:
            return None

        runtime_asm = self.assembly_runtime
        runtime_data_segment_lengths = compile_ir.get_data_segment_lengths(runtime_asm)

        immutables_len = self.compilation_target._metadata["type"].immutable_section_bytes
        runtime_codesize = len(self.bytecode_runtime)

        metadata = bytes.fromhex(self.integrity_sum)
        return compile_ir.generate_cbor_metadata(
            metadata, runtime_codesize, runtime_data_segment_lengths, immutables_len
        )

    @cached_property
    def assembly_runtime(self) -> list:
        if self.settings.experimental_codegen:
            assert self.settings.optimize is not None  # mypy hint
            return generate_assembly_experimental(
                self.venom_runtime, optimize=self.settings.optimize
            )
        else:
            return generate_assembly(self.ir_runtime, self.settings.optimize)

    @cached_property
    def _bytecode(self) -> tuple[bytes, dict[str, Any]]:
        return generate_bytecode(self.assembly)

    @property
    def bytecode(self) -> bytes:
        return self._bytecode[0]

    @property
    def source_map(self) -> dict[str, Any]:
        return self._bytecode[1]

    @cached_property
    def _bytecode_runtime(self) -> tuple[bytes, dict[str, Any]]:
        return generate_bytecode(self.assembly_runtime)

    @property
    def bytecode_runtime(self) -> bytes:
        return self._bytecode_runtime[0]

    @property
    def source_map_runtime(self) -> dict[str, Any]:
        return self._bytecode_runtime[1]

    @cached_property
    def blueprint_bytecode(self) -> bytes:
        blueprint_bytecode = ERC5202_PREFIX + self.bytecode

        # the length of the deployed code in bytes
        len_bytes = len(blueprint_bytecode).to_bytes(2, "big")
        deploy_bytecode = b"\x61" + len_bytes + b"\x3d\x81\x60\x0a\x3d\x39\xf3"

        return deploy_bytecode + blueprint_bytecode


def generate_ir_nodes(global_ctx: ModuleT, settings: Settings) -> tuple[IRnode, IRnode]:
    """
    Generate the intermediate representation (IR) from the contextualized AST.

    This phase also includes IR-level optimizations.

    This function returns three values: deployment bytecode, runtime bytecode
    and the function signatures of the contract

    Arguments
    ---------
    global_ctx: ModuleT
        Contextualized Vyper AST

    Returns
    -------
    (IRnode, IRnode)
        IR to generate deployment bytecode
        IR to generate runtime bytecode
    """
    # make IR output the same between runs
    codegen.reset_names()

    with anchor_settings(settings):
        ir_nodes, ir_runtime = module.generate_ir_for_module(global_ctx)

    if should_run_legacy_optimizer(settings):
        ir_nodes = optimizer.optimize(ir_nodes)
        ir_runtime = optimizer.optimize(ir_runtime)

    return ir_nodes, ir_runtime


def generate_assembly(
    ir_nodes: IRnode,
    optimize: Optional[OptimizationLevel] = None,
    compiler_metadata: Optional[Any] = None,
) -> list:
    """
    Generate assembly instructions from IR.

    Arguments
    ---------
    ir_nodes : str
        Top-level IR nodes. Can be deployment or runtime IR.

    Returns
    -------
    list
        List of assembly instructions.
    """
    optimize = optimize or OptimizationLevel.default()
    assembly = compile_ir.compile_to_assembly(
        ir_nodes, optimize=optimize, compiler_metadata=compiler_metadata
    )

    if "DEBUG" in assembly:
        vyper_warn(
            VyperWarning(
                "This code contains DEBUG opcodes! The DEBUG opcode will only work in "
                "a supported EVM! It will FAIL on all other nodes!"
            )
        )
    return assembly


def generate_bytecode(assembly: list) -> tuple[bytes, dict[str, Any]]:
    """
    Generate bytecode from assembly instructions.

    Arguments
    ---------
    assembly : list
        Assembly instructions. Can be deployment or runtime assembly.

    Returns
    -------
    bytes
        Final compiled bytecode.
    dict
        Source map
    """
    return compile_ir.assembly_to_evm(assembly)
