from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode


# try to fold a node, swallowing exceptions. this function is very similar to
# `VyperNode.get_folded_value()` but additionally checks in the constants
# table if the node is a `Name` node.
#
# CMC 2023-12-30 a potential refactor would be to move this function into
# `Name._try_fold` (which would require modifying the signature of _try_fold to
# take an optional constants table as parameter). this would remove the
# need to use this function in conjunction with `get_descendants` since
# `VyperNode._try_fold()` already recurses. it would also remove the need
# for `VyperNode._set_folded_value()`.
def _fold_with_constants(node: vy_ast.VyperNode, constants: dict[str, vy_ast.VyperNode]):
    if isinstance(node, vy_ast.Name):
        # check if it's in constants table
        var_name = node.id

        if var_name not in constants:
            return

        res = constants[var_name]
        node._set_folded_value(res)
        return

    try:
        # call get_folded_value for its side effects
        node.get_folded_value()
    except UnfoldableNode:
        pass


def _get_constants(node: vy_ast.Module) -> dict:
    constants: dict[str, vy_ast.VyperNode] = {}
    const_var_decls = node.get_children(vy_ast.VariableDecl, {"is_constant": True})

    while len(const_var_decls) > 0:
        n_processed = 0

        for c in const_var_decls.copy():
            assert c.value is not None  # guaranteed by VariableDecl.validate()

            for n in c.get_descendants(reverse=True):
                _fold_with_constants(n, constants)

                try:
                    val = c.value.get_folded_value()
                except UnfoldableNode:
                    # not foldable, maybe it depends on other constants
                    # so try again later
                    continue

            # note that if a constant is redefined, its value will be
            # overwritten, but it is okay because the error is handled
            # downstream
            name = c.target.id
            constants[name] = val

            n_processed += 1
            const_var_decls.remove(c)

        if n_processed == 0:
            # this condition means that there are some constant vardecls
            # whose values are not foldable
            raise UnfoldableNode("unfoldable constants", *const_var_decls)

    return constants


# perform constant folding on a module AST
def pre_typecheck(node: vy_ast.Module) -> None:
    """
    Perform pre-typechecking steps on a Module AST node.
    At this point, this is limited to performing constant folding.
    """
    constants = _get_constants(node)

    # note: use reverse to get descendants in leaf-first order
    for n in node.get_descendants(reverse=True):
        # try folding every single node. note this should be done before
        # type checking because the typechecker requires literals or
        # foldable nodes in type signatures and some other places (e.g.
        # certain builtin kwargs).
        #
        # note we could limit to only folding nodes which are required
        # during type checking, but it's easier to just fold everything
        # and be done with it!
        _fold_with_constants(n, constants)
