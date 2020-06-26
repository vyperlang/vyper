import ast as python_ast
from typing import Dict, Tuple

from vyper.ast import nodes as vy_ast

from vyper.context.namespace import Namespace

from . import node as lll_ast


class LLLTranslator(python_ast.NodeTransformer):
    def __init__(self):
        self.symbol_table = {}
        self.storage_pointer = 0

    def visit_Module(self, node: vy_ast.Module) -> lll_ast.Module:  # type: ignore
        for var in node.storage:
            self.symbol_table[var.name] = self.storage_pointer
            self.storage_pointer += 1
        return lll_ast.Module(self.visit(node.body))  # type: ignore


def convert_ast_to_ir(module: vy_ast.Module) -> Tuple[lll_ast.Module, Dict[str, int]]:
    transformer = LLLTranslator()
    return transformer.visit(module), transformer.symbol_table  # type: ignore
