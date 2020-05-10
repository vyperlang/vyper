import warnings
from typing import (
    Optional,
    Tuple,
)

from vyper import (
    ast as vy_ast,
    compile_lll,
    optimizer,
)
from vyper.parser import (
    parser,
)
from vyper.parser.global_context import (
    GlobalContext,
)
from vyper.typing import (
    InterfaceImports,
)


class CompilerData:
    def __init__(self, contract_name, source_code, interface_codes, source_id):
        self.contract_name = contract_name
        self.source_code = source_code
        self.interface_codes = interface_codes
        self.source_id = source_id

    @property
    def vyper_ast(self):
        if not hasattr(self, "_vyper_ast"):
            self._vyper_ast = generate_ast(self.source_code, self.source_id)
        return self._vyper_ast

    @property
    def global_ctx(self):
        if not hasattr(self, "_global_ctx"):
            self._global_ctx = generate_global_context(self.interface_codes, self.vyper_ast)
        return self._global_ctx

    def _gen_lll(self):
        self._lll_nodes, self._lll_runtime = generate_lll_nodes(
            self.source_code, self.global_ctx
        )

    @property
    def lll_nodes(self):
        if not hasattr(self, "_lll_nodes"):
            self._gen_lll()
        return self._lll_nodes

    @property
    def lll_runtime(self):
        if not hasattr(self, "_lll_runtime"):
            self._gen_lll()
        return self._lll_runtime

    @property
    def assembly(self):
        if not hasattr(self, "_assembly"):
            self._assembly = generate_assembly(self.lll_nodes)
        return self._assembly

    @property
    def assembly_runtime(self):
        if not hasattr(self, "_assembly_runtime"):
            self._assembly_runtime = generate_assembly(self.lll_runtime)
        return self._assembly_runtime

    @property
    def bytecode(self):
        if not hasattr(self, "_bytecode"):
            self._bytecode = generate_bytecode(self.assembly)
        return self._bytecode

    @property
    def bytecode_runtime(self):
        if not hasattr(self, "_bytecode_runtime"):
            self._bytecode_runtime = generate_bytecode(self.assembly_runtime)
        return self._bytecode_runtime


def generate_ast(source_code: str, source_id: int) -> vy_ast.Module:
    return vy_ast.parse_to_ast(source_code, source_id)


def generate_global_context(
    interface_codes: Optional[InterfaceImports], vyper_ast: vy_ast.Module
) -> GlobalContext:
    return GlobalContext.get_global_context(vyper_ast, interface_codes=interface_codes)


def generate_lll_nodes(
    source_code: str, global_ctx: GlobalContext
) -> Tuple[parser.LLLnode, parser.LLLnode]:
    lll_nodes, lll_runtime = parser.parse_tree_to_lll(source_code, global_ctx)
    lll_nodes = optimizer.optimize(lll_nodes)
    lll_runtime = optimizer.optimize(lll_runtime)
    return lll_nodes, lll_runtime


def generate_assembly(lll_nodes: parser.LLLnode) -> list:
    assembly = compile_lll.compile_to_assembly(lll_nodes)
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
    return compile_lll.assembly_to_evm(assembly)[0]
