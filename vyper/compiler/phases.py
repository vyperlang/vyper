import copy
import warnings
from functools import cached_property
from pathlib import Path, PurePath
from typing import Optional, Tuple

from vyper import ast as vy_ast
from vyper.codegen import module
from vyper.codegen.core import anchor_opt_level
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FileInput, FilesystemInputBundle, InputBundle
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import StructureException
from vyper.ir import compile_ir, optimizer
from vyper.semantics import set_data_positions, validate_semantics
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.typing import StorageLayout
from vyper.venom import generate_assembly_experimental, generate_ir

DEFAULT_CONTRACT_PATH = PurePath("VyperContract.vy")


def _merge_one(lhs, rhs, helpstr):
    if lhs is not None and rhs is not None and lhs != rhs:
        raise StructureException(
            f"compiler settings indicate {helpstr} {lhs}, " f"but source pragma indicates {rhs}."
        )
    return lhs if rhs is None else rhs


# TODO: does this belong as a method under Settings?
def _merge_settings(cli: Settings, pragma: Settings):
    ret = Settings()
    ret.evm_version = _merge_one(cli.evm_version, pragma.evm_version, "evm version")
    ret.optimize = _merge_one(cli.optimize, pragma.optimize, "optimize")
    ret.experimental_codegen = _merge_one(
        cli.experimental_codegen, pragma.experimental_codegen, "experimental codegen"
    )

    return ret


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
    vyper_module_folded : vy_ast.Module
        Folded Vyper AST
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
        # to force experimental codegen, uncomment:
        # settings.experimental_codegen = True

        if isinstance(file_input, str):
            file_input = FileInput(
                source_code=file_input,
                source_id=-1,
                path=DEFAULT_CONTRACT_PATH,
                resolved_path=DEFAULT_CONTRACT_PATH,
            )
        self.file_input = file_input
        self.storage_layout_override = storage_layout
        self.show_gas_estimates = show_gas_estimates
        self.no_bytecode_metadata = no_bytecode_metadata
        self.settings = settings or Settings()
        self.input_bundle = input_bundle or FilesystemInputBundle([Path(".")])

        _ = self._generate_ast  # force settings to be calculated

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
            module_path=str(self.contract_path),
            resolved_path=str(self.file_input.resolved_path),
        )

        self.settings = _merge_settings(self.settings, settings)
        if self.settings.optimize is None:
            self.settings.optimize = OptimizationLevel.default()

        if self.settings.experimental_codegen is None:
            self.settings.experimental_codegen = False

        # note self.settings.compiler_version is erased here as it is
        # not used after pre-parsing
        return ast

    @cached_property
    def vyper_module(self):
        return self._generate_ast

    @cached_property
    def vyper_module_unfolded(self) -> vy_ast.Module:
        # This phase is intended to generate an AST for tooling use, and is not
        # used in the compilation process.

        return generate_unfolded_ast(self.vyper_module, self.input_bundle)

    @cached_property
    def _folded_module(self):
        return generate_folded_ast(
            self.vyper_module, self.input_bundle, self.storage_layout_override
        )

    @property
    def vyper_module_folded(self) -> vy_ast.Module:
        module, storage_layout = self._folded_module
        return module

    @property
    def storage_layout(self) -> StorageLayout:
        module, storage_layout = self._folded_module
        return storage_layout

    @property
    def global_ctx(self) -> ModuleT:
        return self.vyper_module_folded._metadata["type"]

    @cached_property
    def _ir_output(self):
        # fetch both deployment and runtime IR
        nodes = generate_ir_nodes(
            self.global_ctx, self.settings.optimize, self.settings.experimental_codegen
        )
        if self.settings.experimental_codegen:
            return [generate_ir(nodes[0]), generate_ir(nodes[1])]
        else:
            return nodes

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

        fs = self.vyper_module_folded.get_children(vy_ast.FunctionDef)
        return {f.name: f._metadata["func_type"] for f in fs}

    @cached_property
    def assembly(self) -> list:
        if self.settings.experimental_codegen:
            return generate_assembly_experimental(
                self.ir_nodes, self.settings.optimize  # type: ignore
            )
        else:
            return generate_assembly(self.ir_nodes, self.settings.optimize)

    @cached_property
    def assembly_runtime(self) -> list:
        if self.settings.experimental_codegen:
            return generate_assembly_experimental(
                self.ir_runtime, self.settings.optimize  # type: ignore
            )
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
        blueprint_preamble = b"\xFE\x71\x00"  # ERC5202 preamble
        blueprint_bytecode = blueprint_preamble + self.bytecode

        # the length of the deployed code in bytes
        len_bytes = len(blueprint_bytecode).to_bytes(2, "big")
        deploy_bytecode = b"\x61" + len_bytes + b"\x3d\x81\x60\x0a\x3d\x39\xf3"

        return deploy_bytecode + blueprint_bytecode


# destructive -- mutates module in place!
def generate_unfolded_ast(vyper_module: vy_ast.Module, input_bundle: InputBundle) -> vy_ast.Module:
    vy_ast.validation.validate_literal_nodes(vyper_module)
    vy_ast.folding.replace_builtin_functions(vyper_module)

    with input_bundle.search_path(Path(vyper_module.resolved_path).parent):
        # note: validate_semantics does type inference on the AST
        validate_semantics(vyper_module, input_bundle)

    return vyper_module


def generate_folded_ast(
    vyper_module: vy_ast.Module,
    input_bundle: InputBundle,
    storage_layout_overrides: StorageLayout = None,
) -> Tuple[vy_ast.Module, StorageLayout]:
    """
    Perform constant folding operations on the Vyper AST.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node

    Returns
    -------
    vy_ast.Module
        Folded Vyper AST
    StorageLayout
        Layout of variables in storage
    """

    vy_ast.validation.validate_literal_nodes(vyper_module)

    vyper_module_folded = copy.deepcopy(vyper_module)
    vy_ast.folding.fold(vyper_module_folded)

    with input_bundle.search_path(Path(vyper_module.resolved_path).parent):
        validate_semantics(vyper_module_folded, input_bundle)

    symbol_tables = set_data_positions(vyper_module_folded, storage_layout_overrides)

    return vyper_module_folded, symbol_tables


def generate_ir_nodes(
    global_ctx: ModuleT, optimize: OptimizationLevel, experimental_codegen: bool
) -> tuple[IRnode, IRnode]:
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
    with anchor_opt_level(optimize):
        ir_nodes, ir_runtime = module.generate_ir_for_module(global_ctx)
    if optimize != OptimizationLevel.NONE:
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
