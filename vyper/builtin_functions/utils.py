from vyper import ast as vy_ast
from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.stmt import parse_body
from vyper.semantics.namespace import Namespace, override_global_namespace
from vyper.semantics.types.function import ContractFunction, FunctionVisibility, StateMutability
from vyper.semantics.validation.local import FunctionNodeVisitor


def _strip_source_pos(ir_node):
    ir_node.source_pos = None
    for x in ir_node.args:
        _strip_source_pos(x)


def generate_inline_function(code, variables, variables_2, memory_allocator):
    ast_code = parse_to_ast(code)
    # Annotate the AST with a temporary old (i.e. typecheck) namespace
    namespace = Namespace()
    namespace.update(variables_2)
    with override_global_namespace(namespace):
        fn_node = vy_ast.FunctionDef()
        fn_node.body = []
        fn_node.args = vy_ast.arguments(defaults=[])
        fn_node._metadata["type"] = ContractFunction(
            "sqrt_builtin",
            {},
            0,
            0,
            None,
            FunctionVisibility.INTERNAL,
            StateMutability.NONPAYABLE,
        )
        sv = FunctionNodeVisitor(ast_code, fn_node, namespace)
        for n in ast_code.body:
            sv.visit(n)

    new_context = Context(
        vars_=variables, global_ctx=GlobalContext(), memory_allocator=memory_allocator
    )
    generated_ir = parse_body(ast_code.body, new_context)
    # strip source position info from the generated_ir since
    # it doesn't make any sense (e.g. the line numbers will start from 0
    # instead of where we are in the code)
    # NOTE if we ever use this for inlining user-code, it would make
    # sense to fix the offsets of the source positions in the generated
    # code instead of stripping them.
    _strip_source_pos(generated_ir)
    return new_context, generated_ir
