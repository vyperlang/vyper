import copy
import warnings
from functools import cached_property
from pathlib import Path, PurePath
from typing import Optional, Tuple

from vyper import ast as vy_ast
from vyper.codegen import module
from vyper.codegen.core import anchor_opt_level
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FilesystemInputBundle, InputBundle
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import StructureException
from vyper.ir import compile_ir, optimizer
from vyper.semantics import set_data_positions, validate_semantics
from vyper.semantics.types.function import ContractFunctionT
from vyper.typing import StorageLayout
from vyper.venom import generate_assembly_experimental, generate_ir

DEFAULT_CONTRACT_NAME = PurePath("VyperContract.vy")


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
    global_ctx : GlobalContext
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
        source_code: str,
        input_bundle: InputBundle = None,
        contract_path: Path | PurePath = DEFAULT_CONTRACT_NAME,
        source_id: int = 0,
        settings: Settings = None,
        storage_layout: StorageLayout = None,
        show_gas_estimates: bool = False,
        no_bytecode_metadata: bool = False,
        experimental_codegen: bool = False,
    ) -> None:
        """
        Initialization method.

        Arguments
        ---------
        source_code: str
            Vyper source code.
        contract_path: Path, optional
            The name of the contract being compiled.
        source_id: int, optional
            ID number used to identify this contract in the source map.
        settings: Settings
            Set optimization mode.
        show_gas_estimates: bool, optional
            Show gas estimates for abi and ir output modes
        no_bytecode_metadata: bool, optional
            Do not add metadata to bytecode. Defaults to False
        experimental_codegen: bool, optional
            Use experimental codegen. Defaults to False
        """
        # to force experimental codegen, uncomment:
        # experimental_codegen = True
        self.contract_path = contract_path
        self.source_code = source_code
        self.source_id = source_id
        self.storage_layout_override = storage_layout
        self.show_gas_estimates = show_gas_estimates
        self.no_bytecode_metadata = no_bytecode_metadata
        self.experimental_codegen = experimental_codegen
        self.settings = settings or Settings()
        self.input_bundle = input_bundle or FilesystemInputBundle([Path(".")])

        _ = self._generate_ast  # force settings to be calculated

    @cached_property
    def _generate_ast(self):
        contract_name = str(self.contract_path)
        settings, ast = generate_ast(self.source_code, self.source_id, contract_name)

        # validate the compiler settings
        # XXX: this is a bit ugly, clean up later
        if settings.evm_version is not None:
            if (
                self.settings.evm_version is not None
                and self.settings.evm_version != settings.evm_version
            ):
                raise StructureException(
                    f"compiler settings indicate evm version {self.settings.evm_version}, "
                    f"but source pragma indicates {settings.evm_version}."
                )

            self.settings.evm_version = settings.evm_version

        if settings.optimize is not None:
            if self.settings.optimize is not None and self.settings.optimize != settings.optimize:
                raise StructureException(
                    f"compiler options indicate optimization mode {self.settings.optimize}, "
                    f"but source pragma indicates {settings.optimize}."
                )
            self.settings.optimize = settings.optimize

        # ensure defaults
        if self.settings.optimize is None:
            self.settings.optimize = OptimizationLevel.default()

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

        return generate_unfolded_ast(self.contract_path, self.vyper_module, self.input_bundle)

    @cached_property
    def _folded_module(self):
        return generate_folded_ast(
            self.contract_path, self.vyper_module, self.input_bundle, self.storage_layout_override
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
    def global_ctx(self) -> GlobalContext:
        return GlobalContext(self.vyper_module_folded)

    @cached_property
    def _ir_output(self):
        # fetch both deployment and runtime IR
        nodes = generate_ir_nodes(self.global_ctx, self.settings.optimize)
        if self.experimental_codegen:
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
        return {f.name: f._metadata["type"] for f in fs}

    @cached_property
    def assembly(self) -> list:
        if self.experimental_codegen:
            return generate_assembly_experimental(
                self.ir_nodes, self.settings.optimize  # type: ignore
            )
        else:
            return generate_assembly(self.ir_nodes, self.settings.optimize)

    @cached_property
    def assembly_runtime(self) -> list:
        if self.experimental_codegen:
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


def generate_ast(
    source_code: str, source_id: int, contract_name: str
) -> tuple[Settings, vy_ast.Module]:
    """
    Generate a Vyper AST from source code.

    Arguments
    ---------
    source_code : str
        Vyper source code.
    source_id : int
        ID number used to identify this contract in the source map.
    contract_name: str
        Name of the contract.

    Returns
    -------
    vy_ast.Module
        Top-level Vyper AST node
    """
    return vy_ast.parse_to_ast_with_settings(source_code, source_id, contract_name)


# destructive -- mutates module in place!
def generate_unfolded_ast(
    contract_path: Path | PurePath, vyper_module: vy_ast.Module, input_bundle: InputBundle
) -> vy_ast.Module:
    vy_ast.validation.validate_literal_nodes(vyper_module)
    vy_ast.folding.replace_builtin_functions(vyper_module)

    with input_bundle.search_path(contract_path.parent):
        # note: validate_semantics does type inference on the AST
        validate_semantics(vyper_module, input_bundle)

    return vyper_module


def generate_folded_ast(
    contract_path: Path,
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

    with input_bundle.search_path(contract_path.parent):
        validate_semantics(vyper_module_folded, input_bundle)

    symbol_tables = set_data_positions(vyper_module_folded, storage_layout_overrides)

    return vyper_module_folded, symbol_tables


def generate_ir_nodes(
    global_ctx: GlobalContext, optimize: OptimizationLevel
) -> tuple[IRnode, IRnode]:
    """
    Generate the intermediate representation (IR) from the contextualized AST.

    This phase also includes IR-level optimizations.

    This function returns three values: deployment bytecode, runtime bytecode
    and the function signatures of the contract

    Arguments
    ---------
    global_ctx : GlobalContext
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
            "a supported EVM! It will FAIL on all other nodes!"
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
