import copy

from vyper import ast
from vyper.exceptions import (
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)
from vyper.parser.context import (
    Context,
)
from vyper.parser.expr import (
    Expr,
)
from vyper.parser.memory_allocator import (
    MemoryAllocator,
)
from vyper.types.types import (
    BaseType,
    ByteArrayType,
)
from vyper.utils import (
    SizeLimits,
    is_instances,
)


class Constants(object):

    def __init__(self):
        self._constants = dict()
        self._constants_ast = dict()

    def __contains__(self, key):
        return key in self._constants

    def unroll_constant(self, const, global_ctx):
        ann_expr = None
        expr = Expr.parse_value_expr(
            const.value,
            Context(
                vars=None,
                global_ctx=global_ctx,
                origcode=const.source_code,
                memory_allocator=MemoryAllocator()
            ),
        )
        annotation_type = global_ctx.parse_type(const.annotation.args[0], None)
        fail = False

        if is_instances([expr.typ, annotation_type], ByteArrayType):
            if expr.typ.maxlen < annotation_type.maxlen:
                return const
            fail = True

        elif expr.typ != annotation_type:
            fail = True
            # special case for literals, which can be uint256 types as well.
            is_special_case_uint256_literal = (
                is_instances([expr.typ, annotation_type], BaseType)
            ) and (
                [annotation_type.typ, expr.typ.typ] == ['uint256', 'int128']
            ) and SizeLimits.in_bounds('uint256', expr.value)

            is_special_case_int256_literal = (
                is_instances([expr.typ, annotation_type], BaseType)
            ) and (
                [annotation_type.typ, expr.typ.typ] == ['int128', 'int128']
            ) and SizeLimits.in_bounds('int128', expr.value)

            if is_special_case_uint256_literal or is_special_case_int256_literal:
                fail = False

        if fail:
            raise TypeMismatchException(
                'Invalid value for constant type, expected %r got %r instead' % (
                    annotation_type,
                    expr.typ,
                ),
                const.value,
            )

        ann_expr = copy.deepcopy(expr)
        ann_expr.typ = annotation_type
        ann_expr.typ.is_literal = expr.typ.is_literal  # Annotation type doesn't have literal set.

        return ann_expr

    def add_constant(self, item, global_ctx):
        args = item.annotation.args
        if not item.value:
            raise StructureException('Constants must express a value!', item)

        is_correctly_formatted_struct = (
            len(args) == 1 and isinstance(args[0], (ast.Subscript, ast.Name, ast.Call))
        ) and item.target

        if is_correctly_formatted_struct:
            c_name = item.target.id
            if global_ctx.is_valid_varname(c_name, item):
                self._constants[c_name] = self.unroll_constant(item, global_ctx)
                self._constants_ast[c_name] = item.value
            # TODO: the previous `if` has no else which will result in this
            # *silently* existing without doing anything. is this intended
            # behavior.
        else:
            raise StructureException('Incorrectly formatted struct', item)

    def ast_is_constant(self, ast_node):
        return isinstance(ast_node, ast.Name) and ast_node.id in self._constants

    def is_constant_of_base_type(self, ast_node, base_types):
        base_types = (base_types) if not isinstance(base_types, tuple) else base_types
        valid = self.ast_is_constant(ast_node)
        if not valid:
            return False

        const = self._constants[ast_node.id]
        if isinstance(const.typ, BaseType) and const.typ.typ in base_types:
            return True

        return False

    def get_constant(self, const_name, context):
        """ Return unrolled const """

        # check if value is compatible with
        const = self._constants[const_name]

        if isinstance(const, ast.AnnAssign):  # Handle ByteArrays.
            if context:
                expr = Expr(const.value, context).lll_node
                return expr
            else:
                raise VariableDeclarationException(
                    "ByteArray: Can not be used outside of a function context: %s" % const_name
                )

        # Other types are already unwrapped, no need
        return self._constants[const_name]
