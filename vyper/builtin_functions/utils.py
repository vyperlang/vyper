from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.stmt import parse_body
from vyper.semantics.validation.annotation import StatementAnnotationVisitor


def generate_inline_function(code, variables, memory_allocator, namespace=None):
    ast_code = parse_to_ast(code)

    if namespace:
        sv = StatementAnnotationVisitor(namespace=namespace)
        for node in ast_code.body:
            sv.visit(node)

    new_context = Context(
        vars_=variables, global_ctx=GlobalContext(), memory_allocator=memory_allocator
    )
    generated_ir = parse_body(ast_code.body, new_context)
    return new_context, generated_ir
