# stub file to factor type checker into
# for now just call into existing code

from vyper.old_codegen.parser_utils import make_setter


# Check assignment from rhs to lhs.
# For now use make_setter for its typechecking side effects
def check_assign(lhs, rhs, pos):
    make_setter(lhs, rhs, pos=pos)
    # TODO Refactor into an actual type-checking function
