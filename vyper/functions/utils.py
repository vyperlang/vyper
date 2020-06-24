from vyper.ast import parse_to_ast
from vyper.parser.context import Context
from vyper.parser.global_context import GlobalContext
from vyper.parser.stmt import parse_body


def generate_inline_function(code, variables, memory_allocator):
    ast_code = parse_to_ast(code)
    new_context = Context(
        vars=variables, global_ctx=GlobalContext(), memory_allocator=memory_allocator, origcode=code
    )
    generated_lll = parse_body(ast_code.body, new_context)
    return new_context, generated_lll
