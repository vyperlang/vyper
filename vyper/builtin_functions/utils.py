from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.stmt import parse_body


def generate_inline_function(code, variables, memory_allocator):
    ast_code = parse_to_ast(code)
    new_context = Context(
        vars_=variables, global_ctx=GlobalContext(), memory_allocator=memory_allocator
    )
    generated_ir = parse_body(ast_code.body, new_context)
    return new_context, generated_ir
