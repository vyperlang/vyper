import ast
from .parser_utils import LLLnode
from .utils import fourbytes_to_int, hex_to_int, bytes_to_int, \
    DECIMAL_DIVISOR, RESERVED_MEMORY, ADDRSIZE_POS, MAXNUM_POS, MINNUM_POS, \
    MAXDECIMAL_POS, MINDECIMAL_POS, FREE_VAR_SPACE, BLANK_SPACE, FREE_LOOP_INDEX

def get_int_at(args, pos):
    if isinstance(args[pos].value, int):
        return args[pos].value
    elif args[pos].value == "mload" and args[pos].args[0].value in (ADDRSIZE_POS, MAXNUM_POS, MINNUM_POS, MAXDECIMAL_POS, MINDECIMAL_POS):
        return {
            ADDRSIZE_POS: 2**160,
            MAXNUM_POS: 2**128 - 1,
            MINNUM_POS: -2**128 + 1,
            MAXDECIMAL_POS: (2**128 - 1) * DECIMAL_DIVISOR,
            MINDECIMAL_POS: (-2**128 + 1) * DECIMAL_DIVISOR,
        }[args[pos].args[0].value]
    else:
        return None

def int_at(args, pos):
    return get_int_at(args, pos) is not None

def search_for_set(node, var):
    if node.value == "set" and node.args[0].value == var:
        return True
    for arg in node.args:
        if search_for_set(arg, var):
            return True
    return False

def replace_with_value(node, var, value):
    if node.value == "with" and node.args[0].value == var:
        return LLLnode(node.value, [node.args[0], replace_with_value(node.args[1], var, value), node.args[2]], node.typ, node.location)
    elif node.value == var:
        return LLLnode(value, [], node.typ, node.location)
    else:
        return LLLnode(node.value, [replace_with_value(arg, var, value) for arg in node.args], node.typ, node.location)

def optimize(node):
    argz = [optimize(arg) for arg in node.args]
    if node.value == "add" and int_at(argz, 0) and int_at(argz, 1):
        return LLLnode(get_int_at(argz, 0) + get_int_at(argz, 1), [], node.typ, None)
    elif node.value == "sub" and int_at(argz, 0) and int_at(argz, 1):
        return LLLnode(get_int_at(argz, 0) - get_int_at(argz, 1), [], node.typ, None)
    elif node.value == "mul" and int_at(argz, 0) and int_at(argz, 1):
        return LLLnode(get_int_at(argz, 0) * get_int_at(argz, 1), [], node.typ, None)
    elif node.value == "div" and int_at(argz, 0) and int_at(argz, 1):
        return LLLnode((get_int_at(argz, 0) % 2**256) // (get_int_at(argz, 1) % 2**256), [], node.typ, None)
    elif node.value == "mod" and int_at(argz, 0) and int_at(argz, 1):
        return LLLnode((get_int_at(argz, 0) % 2**256) % (get_int_at(argz, 1) % 2**256), [], node.typ, None)
    elif node.value == "add" and int_at(argz, 0) and argz[1].value == "add" and int_at(argz[1].args, 0):
        return LLLnode("add", [LLLnode(argz[0].value + argz[1].args[0].value), argz[1].args[1]], node.typ, None)
    elif node.value == "add" and get_int_at(argz, 0) == 0:
        return LLLnode(argz[1].value, argz[1].args, node.typ, node.location)
    elif node.value == "add" and get_int_at(argz, 1) == 0:
        return LLLnode(argz[0].value, argz[0].args, node.typ, node.location)
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1) and int_at(argz, 2):
        if get_int_at(argz, 0) > get_int_at(argz, 1):
            raise Exception("Clamp always fails")
        elif get_int_at(argz, 1) > get_int_at(argz, 2):
            raise Exception("Clamp always fails")
        else:
            return argz[1]
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1):
        if get_int_at(argz, 0) > get_int_at(argz, 1):
            raise Exception("Clamp always fails")
        else:
            return LLLnode("clample", [argz[1], argz[2]], node.typ, None)
    elif node.value == "clamp_nonzero" and int_at(argz, 0):
        if get_int_at(argz, 0) != 0:
            return LLLnode(argz[0].value, [], node.typ, node.location)
        else:
            raise Exception("Clamp always fails")
    # Turns out this is actually not such a good optimization after all
    elif node.value == "with" and int_at(argz, 1) and not search_for_set(argz[2], argz[0].value) and False:
        o = replace_with_value(argz[2], argz[0].value, argz[1].value)
        return o
    else:
        return LLLnode(node.value, argz, node.typ, node.location)
    
