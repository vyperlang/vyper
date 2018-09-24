from vyper.parser.parser_utils import LLLnode
from vyper.utils import LOADED_LIMIT_MAP


def get_int_at(args, pos, signed=False):
    value = args[pos].value

    if isinstance(value, int):
        o = value
    elif value == "mload" and args[pos].args[0].value in LOADED_LIMIT_MAP.keys():
        o = LOADED_LIMIT_MAP[args[pos].args[0].value]
    else:
        return None
    if signed or o < 0:
        return ((o + 2**255) % 2**256) - 2**255
    else:
        return o % 2**256


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
        return LLLnode(node.value, [node.args[0], replace_with_value(node.args[1], var, value), node.args[2]],
                       node.typ, node.location, node.annotation)
    elif node.value == var:
        return LLLnode(value, [], node.typ, node.location, node.annotation)
    else:
        return LLLnode(node.value, [replace_with_value(arg, var, value) for arg in node.args], node.typ, node.location, node.annotation)


arith = {
    "add": (lambda x, y: x + y, '+'),
    "sub": (lambda x, y: x - y, '-'),
    "mul": (lambda x, y: x * y, '*'),
    "div": (lambda x, y: x // y, '/'),
    "mod": (lambda x, y: x % y, '%'),
}


def optimize(node):
    argz = [optimize(arg) for arg in node.args]
    if node.value in arith and int_at(argz, 0) and int_at(argz, 1):
        left, right = get_int_at(argz, 0), get_int_at(argz, 1)
        calcer, symb = arith[node.value]
        new_value = calcer(left, right)
        if argz[0].annotation and argz[1].annotation:
            annotation = argz[0].annotation + symb + argz[1].annotation
        elif argz[0].annotation or argz[1].annotation:
            annotation = (argz[0].annotation or str(left)) + symb + (argz[1].annotation or str(right))
        else:
            annotation = ''
        return LLLnode(new_value, [], node.typ, None, node.pos, annotation, add_gas_estimate=node.add_gas_estimate)
    elif node.value == "add" and int_at(argz, 0) and argz[1].value == "add" and int_at(argz[1].args, 0):
        calcer, symb = arith[node.value]
        if argz[0].annotation and argz[1].args[0].annotation:
            annotation = argz[0].annotation + symb + argz[1].args[0].annotation
        elif argz[0].annotation or argz[1].args[0].annotation:
            annotation = (argz[0].annotation or str(argz[0].value)) + symb + (argz[1].args[0].annotation or str(argz[1].args[0].value))
        else:
            annotation = ''
        return LLLnode("add", [LLLnode(argz[0].value + argz[1].args[0].value, annotation=annotation), argz[1].args[1]],
                       node.typ, None, node.annotation, add_gas_estimate=node.add_gas_estimate)
    elif node.value == "add" and get_int_at(argz, 0) == 0:
        return LLLnode(argz[1].value, argz[1].args, node.typ, node.location, node.pos, argz[1].annotation, add_gas_estimate=node.add_gas_estimate)
    elif node.value == "add" and get_int_at(argz, 1) == 0:
        return LLLnode(argz[0].value, argz[0].args, node.typ, node.location, node.pos, argz[0].annotation, add_gas_estimate=node.add_gas_estimate)
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1) and int_at(argz, 2):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):
            raise Exception("Clamp always fails")
        elif get_int_at(argz, 1, True) > get_int_at(argz, 2, True):
            raise Exception("Clamp always fails")
        else:
            return argz[1]
    elif node.value == "clamp" and int_at(argz, 0) and int_at(argz, 1):
        if get_int_at(argz, 0, True) > get_int_at(argz, 1, True):
            raise Exception("Clamp always fails")
        else:
            return LLLnode("clample", [argz[1], argz[2]], node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
    elif node.value == "clamp_nonzero" and int_at(argz, 0):
        if get_int_at(argz, 0) != 0:
            return LLLnode(argz[0].value, [], node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
        else:
            raise Exception("Clamp always fails")
    # [eq, x, 0] is the same as [iszero, x].
    elif node.value == 'eq' and int_at(argz, 1) and argz[1].value == 0:
        return LLLnode('iszero', [argz[0]], node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
    # Turns out this is actually not such a good optimization after all
    elif node.value == "with" and int_at(argz, 1) and not search_for_set(argz[2], argz[0].value) and False:
        o = replace_with_value(argz[2], argz[0].value, argz[1].value)
        return o
    elif node.value == "seq":
        o = []
        for arg in argz:
            if arg.value == "seq":
                o.extend(arg.args)
            elif arg.value != "pass":
                o.append(arg)
        return LLLnode(node.value, o, node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
    elif hasattr(node, 'total_gas'):
        o = LLLnode(node.value, argz, node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
        o.total_gas = node.total_gas - node.gas + o.gas
        o.func_name = node.func_name
        return o
    else:
        return LLLnode(node.value, argz, node.typ, node.location, node.pos, node.annotation, add_gas_estimate=node.add_gas_estimate)
