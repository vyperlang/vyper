from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.global_context import GlobalContext
from vyper.codegen.stmt import parse_body
from vyper.semantics.analysis.local import FunctionNodeVisitor
from vyper.semantics.namespace import Namespace, override_global_namespace
from vyper.semantics.types.function import ContractFunctionT, FunctionVisibility, StateMutability


def _strip_source_pos(ir_node):
    ir_node.source_pos = None
    for x in ir_node.args:
        _strip_source_pos(x)


def generate_inline_function(code, variables, variables_2, memory_allocator):
    ast_code = parse_to_ast(code, add_fn_node="dummy_fn")
    # Annotate the AST with a temporary old (i.e. typecheck) namespace
    namespace = Namespace()
    namespace.update(variables_2)
    with override_global_namespace(namespace):
        # Initialise a placeholder `FunctionDef` AST node and corresponding
        # `ContractFunctionT` type to rely on the annotation visitors in semantics
        # module.
        ast_code.body[0]._metadata["type"] = ContractFunctionT(
            "sqrt_builtin", [], [], None, FunctionVisibility.INTERNAL, StateMutability.NONPAYABLE
        )
        # The FunctionNodeVisitor's constructor performs semantic checks
        # annotate the AST as side effects.
        FunctionNodeVisitor(ast_code, ast_code.body[0], namespace)

    new_context = Context(
        vars_=variables, global_ctx=GlobalContext(), memory_allocator=memory_allocator
    )
    generated_ir = parse_body(ast_code.body[0].body, new_context)
    # strip source position info from the generated_ir since
    # it doesn't make any sense (e.g. the line numbers will start from 0
    # instead of where we are in the code)
    # NOTE if we ever use this for inlining user-code, it would make
    # sense to fix the offsets of the source positions in the generated
    # code instead of stripping them.
    _strip_source_pos(generated_ir)
    return new_context, generated_ir
