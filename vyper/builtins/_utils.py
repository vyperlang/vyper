from vyper.ast import parse_to_ast
from vyper.codegen.context import Context
from vyper.codegen.stmt import parse_body
from vyper.semantics.analysis.local import FunctionAnalyzer
from vyper.semantics.namespace import Namespace, override_global_namespace
from vyper.semantics.types.function import ContractFunctionT, FunctionVisibility, StateMutability
from vyper.semantics.types.module import ModuleT


def _strip_ast_source(ir_node):
    ir_node.ast_source = None
    for x in ir_node.args:
        _strip_ast_source(x)


def generate_inline_function(code, variables, variables_2, memory_allocator):
    ast_code = parse_to_ast(code, add_fn_node="dummy_fn")
    # Annotate the AST with a temporary old (i.e. typecheck) namespace
    namespace = Namespace()
    namespace.update(variables_2)
    with override_global_namespace(namespace):
        # Initialise a placeholder `FunctionDef` AST node and corresponding
        # `ContractFunctionT` type to rely on the annotation visitors in semantics
        # module.
        ast_code.body[0]._metadata["func_type"] = ContractFunctionT(
            "sqrt_builtin", [], [], None, FunctionVisibility.INTERNAL, StateMutability.NONPAYABLE
        )
        analyzer = FunctionAnalyzer(ast_code, ast_code.body[0], namespace)
        analyzer.analyze()

    new_context = Context(
        vars_=variables, module_ctx=ModuleT(ast_code), memory_allocator=memory_allocator
    )
    generated_ir = parse_body(ast_code.body[0].body, new_context)
    # strip source position info from the generated_ir since
    # it doesn't make any sense (e.g. the line numbers will start from 0
    # instead of where we are in the code)
    # NOTE if we ever use this for inlining user-code, it would make
    # sense to fix the offsets of the source positions in the generated
    # code instead of stripping them.
    _strip_ast_source(generated_ir)
    return new_context, generated_ir
