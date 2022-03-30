from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.stmt import parse_body


def _strip_source_pos(ir_node):
    ir_node.source_pos = None
    for x in ir_node.args:
        _strip_source_pos(x)


def generate_inline_function(code, variables, memory_allocator):
    ast_code = parse_to_ast(code)
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
