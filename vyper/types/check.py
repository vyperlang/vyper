# stub file to factor type checker into
# for now just call into existing code

from vyper.parser.parser_utils import make_setter


# Check assignment from rhs to lhs.
# For now use make_setter for its typechecking side effects
def check_assign(lhs, rhs, pos, in_function_call=False):
    make_setter(lhs, rhs, location="memory", pos=pos, in_function_call=in_function_call)
    # TODO Refactor into an actual type-checking function
