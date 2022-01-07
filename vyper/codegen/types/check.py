# stub file to factor type checker into
# for now just call into existing code

from vyper.codegen.core import make_setter


# Check assignment from rhs to lhs.
# For now use make_setter for its typechecking side effects
def check_assign(lhs, rhs, context, pos):
    make_setter(lhs, rhs, context, pos=pos)
    # TODO Refactor into an actual type-checking function
