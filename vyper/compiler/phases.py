import copy
import warnings
from typing import Optional, Tuple

from vyper import ast as vy_ast
from vyper.ast.signatures.function_signature import FunctionSignatures
from vyper.codegen import module
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir, optimizer
from vyper.semantics import set_data_positions, validate_semantics
from vyper.typing import InterfaceImports, StorageLayout


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
        contract_name: str = "VyperContract",
        interface_codes: Optional[InterfaceImports] = None,
        source_id: int = 0,
        no_optimize: bool = False,
        storage_layout: StorageLayout = None,
        show_gas_estimates: bool = False,
    ) -> None:
        """
        Initialization method.

        Arguments
        ---------
        source_code : str
            Vyper source code.
        contract_name : str, optional
            The name of the contract being compiled.
        interface_codes: Dict, optional
            Interfaces that may be imported by the contracts during compilation.
            * Formatted as as `{'interface name': {'type': "json/vyper", 'code': "interface code"}}`
            * JSON interfaces are given as lists, vyper interfaces as strings
        source_id : int, optional
            ID number used to identify this contract in the source map.
        no_optimize: bool, optional
            Turn off optimizations. Defaults to False
        show_gas_estimates: bool, optional
            Show gas estimates for abi and ir output modes
        """
        self.contract_name = contract_name
        self.source_code = source_code
        self.interface_codes = interface_codes
        self.source_id = source_id
        self.no_optimize = no_optimize
        self.storage_layout_override = storage_layout
        self.show_gas_estimates = show_gas_estimates

    @property
    def vyper_module(self) -> vy_ast.Module:
        if not hasattr(self, "_vyper_module"):
            self._vyper_module = generate_ast(self.source_code, self.source_id, self.contract_name)

        return self._vyper_module

    @property
    def vyper_module_folded(self) -> vy_ast.Module:
        if not hasattr(self, "_vyper_module_folded"):
            self._vyper_module_folded, self._storage_layout = generate_folded_ast(
                self.vyper_module, self.interface_codes, self.storage_layout_override
            )

        return self._vyper_module_folded

    @property
    def storage_layout(self) -> StorageLayout:
        if not hasattr(self, "_storage_layout"):
            self._vyper_module_folded, self._storage_layout = generate_folded_ast(
                self.vyper_module, self.interface_codes, self.storage_layout_override
            )

        return self._storage_layout

    @property
    def global_ctx(self) -> GlobalContext:
        if not hasattr(self, "_global_ctx"):
            self._global_ctx = generate_global_context(
                self.vyper_module_folded, self.interface_codes
            )

        return self._global_ctx

    def _gen_ir(self) -> None:
        # fetch both deployment and runtime IR
        self._ir_nodes, self._ir_runtime, self._function_signatures = generate_ir_nodes(
            self.global_ctx, self.no_optimize
        )

    @property
    def ir_nodes(self) -> IRnode:
        if not hasattr(self, "_ir_nodes"):
            self._gen_ir()
        return self._ir_nodes

    @property
    def ir_runtime(self) -> IRnode:
        if not hasattr(self, "_ir_runtime"):
            self._gen_ir()
        return self._ir_runtime

    @property
    def function_signatures(self) -> FunctionSignatures:
        if not hasattr(self, "_function_signatures"):
            self._gen_ir()
        return self._function_signatures

    @property
    def assembly(self) -> list:
        if not hasattr(self, "_assembly"):
            self._assembly = generate_assembly(self.ir_nodes, self.no_optimize)
        return self._assembly

    @property
    def assembly_runtime(self) -> list:
        if not hasattr(self, "_assembly_runtime"):
            self._assembly_runtime = generate_assembly(self.ir_runtime, self.no_optimize)
        return self._assembly_runtime

    @property
    def bytecode(self) -> bytes:
        if not hasattr(self, "_bytecode"):
            self._bytecode = generate_bytecode(self.assembly)
        return self._bytecode

    @property
    def bytecode_runtime(self) -> bytes:
        if not hasattr(self, "_bytecode_runtime"):
            self._bytecode_runtime = generate_bytecode(self.assembly_runtime)
        return self._bytecode_runtime


def generate_ast(source_code: str, source_id: int, contract_name: str) -> vy_ast.Module:
    """
    Generate a Vyper AST from source code.

    Arguments
    ---------
    source_code : str
        Vyper source code.
    source_id : int
        ID number used to identify this contract in the source map.
    contract_name : str
        Name of the contract.

    Returns
    -------
    vy_ast.Module
        Top-level Vyper AST node
    """
    return vy_ast.parse_to_ast(source_code, source_id, contract_name)


def generate_folded_ast(
    vyper_module: vy_ast.Module,
    interface_codes: Optional[InterfaceImports],
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
    validate_semantics(vyper_module_folded, interface_codes)
    vy_ast.expansion.expand_annotated_ast(vyper_module_folded)
    symbol_tables = set_data_positions(vyper_module_folded, storage_layout_overrides)

    return vyper_module_folded, symbol_tables


def generate_global_context(
    vyper_module: vy_ast.Module,
    interface_codes: Optional[InterfaceImports],
) -> GlobalContext:
    """
    Generate a contextualized AST from the Vyper AST.

    Arguments
    ---------
    vyper_module : vy_ast.Module
        Top-level Vyper AST node
    interface_codes: Dict, optional
        Interfaces that may be imported by the contracts.

    Returns
    -------
    GlobalContext
        Sorted, contextualized representation of the Vyper AST
    """
    return GlobalContext.get_global_context(vyper_module, interface_codes=interface_codes)


def generate_ir_nodes(
    global_ctx: GlobalContext, no_optimize: bool
) -> Tuple[IRnode, IRnode, FunctionSignatures]:
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
    ir_nodes, ir_runtime, function_sigs = module.parse_tree_to_ir(global_ctx)
    if not no_optimize:
        ir_nodes = optimizer.optimize(ir_nodes)
        ir_runtime = optimizer.optimize(ir_runtime)
    return ir_nodes, ir_runtime, function_sigs


def generate_assembly(ir_nodes: IRnode, no_optimize: bool = False) -> list:
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
    assembly = compile_ir.compile_to_assembly(ir_nodes, no_optimize=no_optimize)

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


def generate_bytecode(assembly: list) -> bytes:
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
    return compile_ir.assembly_to_evm(assembly)[0]
