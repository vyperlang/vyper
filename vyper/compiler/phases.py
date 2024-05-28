import copy
import warnings
from functools import cached_property
from pathlib import Path, PurePath
from typing import Optional

from vyper import ast as vy_ast
from vyper.ast import natspec
from vyper.codegen import module
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FileInput, FilesystemInputBundle, InputBundle
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings, merge_settings
from vyper.ir import compile_ir, optimizer
from vyper.semantics import analyze_module, set_data_positions, validate_compilation_target
from vyper.semantics.analysis.data_positions import generate_layout_export
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.typing import StorageLayout
from vyper.utils import ERC5202_PREFIX, vyper_warn
from vyper.venom import generate_assembly_experimental, generate_ir

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
        storage_layout: StorageLayout = None,
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

        # ast cache, hitchhike onto the input_bundle object
        self.input_bundle._cache._ast_of: dict[int, vy_ast.Module] = {}  # type: ignore

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
    def _generate_ast(self):
        settings, ast = vy_ast.parse_to_ast_with_settings(
            self.source_code,
            self.source_id,
            module_path=self.contract_path.as_posix(),
            resolved_path=self.file_input.resolved_path.as_posix(),
        )

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

        return settings, ast

    @cached_property
    def settings(self):
        settings, _ = self._generate_ast
        return settings

    @cached_property
    def vyper_module(self):
        _, ast = self._generate_ast
        return ast

    @cached_property
    def _annotate(self) -> tuple[natspec.NatspecOutput, vy_ast.Module]:
        module = generate_annotated_ast(self.vyper_module, self.input_bundle)
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

        expected = self.expected_integrity_sum

        if expected is not None and module_t.integrity_sum != expected:
            # warn for now. strict/relaxed mode was considered but it costs
            # interface and testing complexity to add another feature flag.
            vyper_warn(
                f"Mismatched integrity sum! Expected {expected}"
                f" but got {module_t.integrity_sum}."
                " (This likely indicates a corrupted archive)"
            )

        validate_compilation_target(module_t)
        return self.annotated_vyper_module

    @cached_property
    def storage_layout(self) -> StorageLayout:
        module_ast = self.compilation_target
        set_data_positions(module_ast, self.storage_layout_override)

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
    def venom_functions(self):
        deploy_ir, runtime_ir = self._ir_output
        deploy_venom = generate_ir(deploy_ir, self.settings.optimize)
        runtime_venom = generate_ir(runtime_ir, self.settings.optimize)
        return deploy_venom, runtime_venom

    @cached_property
    def assembly(self) -> list:
        if self.settings.experimental_codegen:
            deploy_code, runtime_code = self.venom_functions
            assert self.settings.optimize is not None  # mypy hint
            return generate_assembly_experimental(
                runtime_code, deploy_code=deploy_code, optimize=self.settings.optimize
            )
        else:
            return generate_assembly(self.ir_nodes, self.settings.optimize)

    @cached_property
    def assembly_runtime(self) -> list:
        if self.settings.experimental_codegen:
            _, runtime_code = self.venom_functions
            assert self.settings.optimize is not None  # mypy hint
            return generate_assembly_experimental(runtime_code, optimize=self.settings.optimize)
        else:
            return generate_assembly(self.ir_runtime, self.settings.optimize)

    @cached_property
    def bytecode(self) -> bytes:
        insert_compiler_metadata = not self.no_bytecode_metadata
        return generate_bytecode(self.assembly, insert_compiler_metadata=insert_compiler_metadata)

    @cached_property
    def bytecode_runtime(self) -> bytes:
        return generate_bytecode(self.assembly_runtime, insert_compiler_metadata=False)

    @cached_property
    def blueprint_bytecode(self) -> bytes:
        blueprint_bytecode = ERC5202_PREFIX + self.bytecode

        # the length of the deployed code in bytes
        len_bytes = len(blueprint_bytecode).to_bytes(2, "big")
        deploy_bytecode = b"\x61" + len_bytes + b"\x3d\x81\x60\x0a\x3d\x39\xf3"

        return deploy_bytecode + blueprint_bytecode


def generate_annotated_ast(vyper_module: vy_ast.Module, input_bundle: InputBundle) -> vy_ast.Module:
    """
    Validates and annotates the Vyper AST.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node

    Returns
    -------
    vy_ast.Module
        Annotated Vyper AST
    """
    vyper_module = copy.deepcopy(vyper_module)
    with input_bundle.search_path(Path(vyper_module.resolved_path).parent):
        # note: analyze_module does type inference on the AST
        analyze_module(vyper_module, input_bundle)

    return vyper_module


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
    with anchor_settings(settings):
        ir_nodes, ir_runtime = module.generate_ir_for_module(global_ctx)
    if settings.optimize != OptimizationLevel.NONE:
        ir_nodes = optimizer.optimize(ir_nodes)
        ir_runtime = optimizer.optimize(ir_runtime)
    return ir_nodes, ir_runtime


def generate_assembly(ir_nodes: IRnode, optimize: Optional[OptimizationLevel] = None) -> list:
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
    assembly = compile_ir.compile_to_assembly(ir_nodes, optimize=optimize)

    if _find_nested_opcode(assembly, "DEBUG"):
        warnings.warn(
            "This code contains DEBUG opcodes! The DEBUG opcode will only work in "
            "a supported EVM! It will FAIL on all other nodes!",
            stacklevel=2,
        )
    return assembly


def _find_nested_opcode(assembly, key):
    if key in assembly:
        return True
    else:
        sublists = [sub for sub in assembly if isinstance(sub, list)]
        return any(_find_nested_opcode(x, key) for x in sublists)


def generate_bytecode(assembly: list, insert_compiler_metadata: bool) -> bytes:
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
    """
    return compile_ir.assembly_to_evm(assembly, insert_compiler_metadata=insert_compiler_metadata)[
        0
    ]
