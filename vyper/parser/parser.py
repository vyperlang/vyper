import ast
import copy


from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
    FunctionDeclarationException,
    EventDeclarationException
)
from vyper.signatures.function_signature import (
    FunctionSignature,
    VariableRecord,
)
from vyper.signatures.event_signature import (
    EventSignature,
)
from vyper.parser.stmt import Stmt
from vyper.parser.expr import Expr
from vyper.parser.context import Context
from vyper.parser.global_context import GlobalContext
from vyper.parser.lll_node import LLLnode
from vyper.parser.pre_parser import pre_parse
from vyper.parser.parser_utils import (
    pack_arguments,
    make_setter,
    base_type_conversion,
    byte_array_to_num,
    decorate_ast_with_source,
    getpos,
    make_byte_array_copier,
    resolve_negative_literals,
    unwrap_location,
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    ListType,
)
from vyper.types import (
    get_size_of_type,
    is_base_type,
    ceil32,
)
from vyper.utils import (
    MemoryPositions,
    LOADED_LIMIT_MAP,
    string_to_bytes,
)
from vyper.utils import (
    bytes_to_int,
    calc_mem_gas,
)


if not hasattr(ast, 'AnnAssign'):
    raise Exception("Requires python 3.6 or higher for annotation support")


# Converts code to parse tree
def parse(code):
    code = pre_parse(code)
    o = ast.parse(code)
    decorate_ast_with_source(o, code)
    o = resolve_negative_literals(o)
    return o.body


# Header code
initializer_list = ['seq', ['mstore', 28, ['calldataload', 0]]]
# Store limit constants at fixed addresses in memory.
initializer_list += [['mstore', pos, limit_size] for pos, limit_size in LOADED_LIMIT_MAP.items()]
initializer_lll = LLLnode.from_list(initializer_list, typ=None)


# Is a function the initializer?
def is_initializer(code):
    return code.name == '__init__'


# Is a function the default function?
def is_default_func(code):
    return code.name == '__default__'


# Generate default argument function signatures.
def generate_default_arg_sigs(code, _contracts, _custom_units):
    # generate all sigs, and attach.
    total_default_args = len(code.args.defaults)
    if total_default_args == 0:
        return [FunctionSignature.from_definition(code, sigs=_contracts, custom_units=_custom_units)]
    base_args = code.args.args[:-total_default_args]
    default_args = code.args.args[-total_default_args:]

    # Generate a list of default function combinations.
    row = [False] * (total_default_args)
    table = [row.copy()]
    for i in range(total_default_args):
        row[i] = True
        table.append(row.copy())

    default_sig_strs = []
    sig_fun_defs = []
    for truth_row in table:
        new_code = copy.deepcopy(code)
        new_code.args.args = copy.deepcopy(base_args)
        new_code.args.default = []
        # Add necessary default args.
        for idx, val in enumerate(truth_row):
            if val is True:
                new_code.args.args.append(default_args[idx])
        sig = FunctionSignature.from_definition(new_code, sigs=_contracts, custom_units=_custom_units)
        default_sig_strs.append(sig.sig)
        sig_fun_defs.append(sig)

    return sig_fun_defs


# Get ABI signature
def mk_full_signature(code):
    o = []
    global_ctx = GlobalContext.get_global_context(code)

    for code in global_ctx._events:
        sig = EventSignature.from_declaration(code, custom_units=global_ctx._custom_units)
        o.append(sig.to_abi_dict())
    for code in global_ctx._defs:
        sig = FunctionSignature.from_definition(code, sigs=global_ctx._contracts, custom_units=global_ctx._custom_units)
        if not sig.private:
            default_sigs = generate_default_arg_sigs(code, global_ctx._contracts, global_ctx._custom_units)
            for s in default_sigs:
                o.append(s.to_abi_dict())
    return o


def parse_events(sigs, _events, custom_units=None):
    for event in _events:
        sigs[event.target.id] = EventSignature.from_declaration(event, custom_units=custom_units)
    return sigs


def parse_external_contracts(external_contracts, _contracts):
    for _contractname in _contracts:
        _contract_defs = _contracts[_contractname]
        _defnames = [_def.name for _def in _contract_defs]
        contract = {}
        if len(set(_defnames)) < len(_contract_defs):
            raise FunctionDeclarationException("Duplicate function name: %s" % [name for name in _defnames if _defnames.count(name) > 1][0])

        for _def in _contract_defs:
            constant = False
            # test for valid call type keyword.
            if len(_def.body) == 1 and \
               isinstance(_def.body[0], ast.Expr) and \
               isinstance(_def.body[0].value, ast.Name) and \
               _def.body[0].value.id in ('modifying', 'constant'):
                constant = True if _def.body[0].value.id == 'constant' else False
            else:
                raise StructureException('constant or modifying call type must be specified', _def)
            sig = FunctionSignature.from_definition(_def, contract_def=True, constant=constant)
            contract[sig.name] = sig
        external_contracts[_contractname] = contract
    return external_contracts


def parse_other_functions(o, otherfuncs, sigs, external_contracts, origcode, global_ctx, default_function, runtime_only):
    sub = ['seq', initializer_lll]
    add_gas = initializer_lll.gas
    for _def in otherfuncs:
        sub.append(parse_func(_def, {**{'self': sigs}, **external_contracts}, origcode, global_ctx))  # noqa E999
        sub[-1].total_gas += add_gas
        add_gas += 30
        for sig in generate_default_arg_sigs(_def, external_contracts, global_ctx._custom_units):
            sig.gas = sub[-1].total_gas
            sigs[sig.sig] = sig

    # Add fallback function
    if default_function:
        default_func = parse_func(default_function[0], {**{'self': sigs}, **external_contracts}, origcode, global_ctx)
        sub.append(default_func)
    else:
        sub.append(LLLnode.from_list(['revert', 0, 0], typ=None, annotation='Default function'))
    if runtime_only:
        return sub
    else:
        o.append(['return', 0, ['lll', sub, 0]])
        return o


# Main python parse tree => LLL method
def parse_tree_to_lll(code, origcode, runtime_only=False):
    global_ctx = GlobalContext.get_global_context(code)
    _names_def = [_def.name for _def in global_ctx._defs]
    # Checks for duplicate function names
    if len(set(_names_def)) < len(_names_def):
        raise FunctionDeclarationException("Duplicate function name: %s" % [name for name in _names_def if _names_def.count(name) > 1][0])
    _names_events = [_event.target.id for _event in global_ctx._events]
    # Checks for duplicate event names
    if len(set(_names_events)) < len(_names_events):
        raise EventDeclarationException("Duplicate event name: %s" % [name for name in _names_events if _names_events.count(name) > 1][0])
    # Initialization function
    initfunc = [_def for _def in global_ctx._defs if is_initializer(_def)]
    # Default function
    defaultfunc = [_def for _def in global_ctx._defs if is_default_func(_def)]
    # Regular functions
    otherfuncs = [_def for _def in global_ctx._defs if not is_initializer(_def) and not is_default_func(_def)]
    sigs = {}
    external_contracts = {}
    # Create the main statement
    o = ['seq']
    if global_ctx._events:
        sigs = parse_events(sigs, global_ctx._events, global_ctx._custom_units)
    if global_ctx._contracts:
        external_contracts = parse_external_contracts(external_contracts, global_ctx._contracts)
    # If there is an init func...
    if initfunc:
        o.append(['seq', initializer_lll])
        o.append(parse_func(initfunc[0], {**{'self': sigs}, **external_contracts}, origcode, global_ctx))
    # If there are regular functions...
    if otherfuncs or defaultfunc:
        o = parse_other_functions(
            o, otherfuncs, sigs, external_contracts, origcode, global_ctx, defaultfunc, runtime_only
        )
    return LLLnode.from_list(o, typ=None)


# Checks that an input matches its type
def make_clamper(datapos, mempos, typ, is_init=False):
    if not is_init:
        data_decl = ['calldataload', ['add', 4, datapos]]
        copier = lambda pos, sz: ['calldatacopy', mempos, ['add', 4, pos], sz]
    else:
        data_decl = ['codeload', ['add', '~codelen', datapos]]
        copier = lambda pos, sz: ['codecopy', mempos, ['add', '~codelen', pos], sz]
    # Numbers: make sure they're in range
    if is_base_type(typ, 'int128'):
        return LLLnode.from_list(['clamp', ['mload', MemoryPositions.MINNUM], data_decl, ['mload', MemoryPositions.MAXNUM]],
                                 typ=typ, annotation='checking int128 input')
    # Booleans: make sure they're zero or one
    elif is_base_type(typ, 'bool'):
        return LLLnode.from_list(['uclamplt', data_decl, 2], typ=typ, annotation='checking bool input')
    # Addresses: make sure they're in range
    elif is_base_type(typ, 'address'):
        return LLLnode.from_list(['uclamplt', data_decl, ['mload', MemoryPositions.ADDRSIZE]], typ=typ, annotation='checking address input')
    # Bytes: make sure they have the right size
    elif isinstance(typ, ByteArrayType):
        return LLLnode.from_list(['seq',
                                    copier(data_decl, 32 + typ.maxlen),
                                    ['assert', ['le', ['calldataload', ['add', 4, data_decl]], typ.maxlen]]],
                                 typ=None, annotation='checking bytearray input')
    # Lists: recurse
    elif isinstance(typ, ListType):
        o = []
        for i in range(typ.count):
            offset = get_size_of_type(typ.subtype) * 32 * i
            o.append(make_clamper(datapos + offset, mempos + offset, typ.subtype, is_init))
        return LLLnode.from_list(['seq'] + o, typ=None, annotation='checking list input')
    # Otherwise don't make any checks
    else:
        return LLLnode.from_list('pass')


def get_sig_statements(sig, pos):
    method_id_node = LLLnode.from_list(sig.method_id, pos=pos, annotation='%s' % sig.sig)

    if sig.private:
        sig_compare = 0
        private_label = LLLnode.from_list(
            ['label', 'priv_{}'.format(sig.method_id)],
            pos=pos, annotation='%s' % sig.sig
        )
    else:
        sig_compare = ['eq', ['mload', 0], method_id_node]
        private_label = ['pass']

    return sig_compare, private_label


def get_arg_copier(sig, total_size, memory_dest, offset=4):
    # Copy arguments.
    # For private function, MSTORE arguments and callback pointer from the stack.
    if sig.private:
        copier = ['seq']
        for pos in range(0, total_size, 32):
            copier.append(['mstore', memory_dest + pos, 'pass'])
    else:
        copier = ['calldatacopy', memory_dest, offset, total_size]

    return copier


def make_unpacker(ident, i_placeholder, begin_pos):
    start_label = 'dyn_unpack_start_' + ident
    end_label = 'dyn_unpack_end_' + ident
    return ['seq_unchecked',
        ['mstore', begin_pos, 'pass'],  # get len
        ['mstore', i_placeholder, 0],
        ['label', start_label],
        ['if', ['ge', ['mload', i_placeholder], ['ceil32', ['mload', begin_pos]]], ['goto', end_label]],  # break
        ['mstore', ['add', ['add', begin_pos, 32], ['mload', i_placeholder]], 'pass'],  # pop into correct memory slot.
        ['mstore', i_placeholder, ['add', 32, ['mload', i_placeholder]]],  # increment i
        ['goto', start_label],
        ['label', end_label]]


# Parses a function declaration
def parse_func(code, sigs, origcode, global_ctx, _vars=None):
    if _vars is None:
        _vars = {}
    sig = FunctionSignature.from_definition(code, sigs=sigs, custom_units=global_ctx._custom_units)
    # Get base args for function.
    total_default_args = len(code.args.defaults)
    base_args = sig.args[:-total_default_args] if total_default_args > 0 else sig.args
    default_args = code.args.args[-total_default_args:]
    default_values = dict(zip([arg.arg for arg in default_args], code.args.defaults))
    # __init__ function may not have defaults.
    if sig.name == '__init__' and total_default_args > 0:
        raise FunctionDeclarationException("__init__ function may not have default parameters.")
    # Check for duplicate variables with globals
    for arg in sig.args:
        if arg.name in global_ctx._globals:
            raise FunctionDeclarationException("Variable name duplicated between function arguments and globals: " + arg.name)

    # Create a local (per function) context.
    context = Context(
        vars=_vars,
        global_ctx=global_ctx,
        sigs=sigs,
        return_type=sig.output_type,
        is_constant=sig.const,
        is_payable=sig.payable,
        origcode=origcode,
        is_private=sig.private,
        method_id=sig.method_id
    )

    # Copy calldata to memory for fixed-size arguments
    max_copy_size = sum([32 if isinstance(arg.typ, ByteArrayType) else get_size_of_type(arg.typ) * 32 for arg in sig.args])
    base_copy_size = sum([32 if isinstance(arg.typ, ByteArrayType) else get_size_of_type(arg.typ) * 32 for arg in base_args])
    context.next_mem += max_copy_size

    clampers = []

    # Create callback_ptr, this stores a destination in the bytecode for a private
    # function to jump to after a function has executed.
    _post_callback_ptr = "{}_{}_post_callback_ptr".format(sig.name, sig.method_id)
    if sig.private:
        context.callback_ptr = context.new_placeholder(typ=BaseType('uint256'))
        clampers.append(
            LLLnode.from_list(['mstore', context.callback_ptr, 'pass'], annotation='pop callback pointer')
        )
        if total_default_args > 0:
            clampers.append(['label', _post_callback_ptr])

    # private functions without return types need to jump back to
    # the calling function, as there is no return statement to handle the
    # jump.
    stop_func = [['stop']]
    if sig.output_type is None and sig.private:
        stop_func = [['jump', ['mload', context.callback_ptr]]]

    if not len(base_args):
        copier = 'pass'
    elif sig.name == '__init__':
        copier = ['codecopy', MemoryPositions.RESERVED_MEMORY, '~codelen', base_copy_size]
    else:
        copier = get_arg_copier(
            sig=sig,
            total_size=base_copy_size,
            memory_dest=MemoryPositions.RESERVED_MEMORY
        )
    clampers.append(copier)

    # Add asserts for payable and internal
    # private never gets payable check.
    if not sig.payable and not sig.private:
        clampers.append(['assert', ['iszero', 'callvalue']])

    # Fill variable positions
    for i, arg in enumerate(sig.args):
        if i < len(base_args) and not sig.private:
            clampers.append(make_clamper(arg.pos, context.next_mem, arg.typ, sig.name == '__init__'))
        if isinstance(arg.typ, ByteArrayType):
            context.vars[arg.name] = VariableRecord(arg.name, context.next_mem, arg.typ, False)
            context.next_mem += 32 * get_size_of_type(arg.typ)
        else:
            context.vars[arg.name] = VariableRecord(arg.name, MemoryPositions.RESERVED_MEMORY + arg.pos, arg.typ, False)

    # Private function copiers. No clamping for private functions.
    dyn_variable_names = [a.name for a in base_args if isinstance(a.typ, ByteArrayType)]
    if sig.private and dyn_variable_names:
        i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
        unpackers = []
        for idx, var_name in enumerate(dyn_variable_names):
            var = context.vars[var_name]
            ident = "_load_args_%d_dynarg%d" % (sig.method_id, idx)
            o = make_unpacker(ident=ident, i_placeholder=i_placeholder, begin_pos=var.pos)
            unpackers.append(o)

        if not unpackers:
            unpackers = ['pass']

        clampers.append(LLLnode.from_list(
            ['seq_unchecked'] +
            unpackers +
            [0],  # [0] to complete full overarching 'seq' statement, see private_label.
            typ=None, annotation='dynamic unpacker', pos=getpos(code))
        )

    # Create "clampers" (input well-formedness checkers)
    # Return function body
    if sig.name == '__init__':
        o = LLLnode.from_list(['seq'] + clampers + [parse_body(code.body, context)], pos=getpos(code))
    elif is_default_func(sig):
        if len(sig.args) > 0:
            raise FunctionDeclarationException('Default function may not receive any arguments.', code)
        if sig.private:
            raise FunctionDeclarationException('Default function may only be public.', code)
        o = LLLnode.from_list(['seq'] + clampers + [parse_body(code.body, context)], pos=getpos(code))
    else:

        if total_default_args > 0:  # Function with default parameters.
            function_routine = "{}_{}".format(sig.name, sig.method_id)
            default_sigs = generate_default_arg_sigs(code, sigs, global_ctx._custom_units)
            sig_chain = ['seq']

            for default_sig in default_sigs:
                sig_compare, private_label = get_sig_statements(default_sig, getpos(code))

                # Populate unset default variables
                populate_arg_count = len(sig.args) - len(default_sig.args)
                set_defaults = []
                if populate_arg_count > 0:
                    current_sig_arg_names = {x.name for x in default_sig.args}
                    missing_arg_names = [arg.arg for arg in default_args if arg.arg not in current_sig_arg_names]
                    for arg_name in missing_arg_names:
                        value = Expr(default_values[arg_name], context).lll_node
                        var = context.vars[arg_name]
                        left = LLLnode.from_list(var.pos, typ=var.typ, location='memory',
                                                 pos=getpos(code), mutable=var.mutable)
                        set_defaults.append(make_setter(left, value, 'memory', pos=getpos(code)))

                current_sig_arg_names = {x.name for x in default_sig.args}
                base_arg_names = {arg.name for arg in base_args}
                if sig.private:
                    # Load all variables in default section, if private,
                    # because the stack is a linear pipe.
                    copier_arg_count = len(default_sig.args)
                    copier_arg_names = current_sig_arg_names
                else:
                    copier_arg_count = len(default_sig.args) - len(base_args)
                    copier_arg_names = current_sig_arg_names - base_arg_names
                # Order copier_arg_names, this is very important.
                copier_arg_names = [x.name for x in default_sig.args if x.name in copier_arg_names]

                # Variables to be populated from calldata/stack.
                default_copiers = []
                if copier_arg_count > 0:
                    # Get map of variables in calldata, with thier offsets
                    offset = 4
                    calldata_offset_map = {}
                    for arg in default_sig.args:
                        calldata_offset_map[arg.name] = offset
                        offset += 32 if isinstance(arg.typ, ByteArrayType) else get_size_of_type(arg.typ) * 32
                    # Copy set default parameters from calldata
                    dynamics = []
                    for arg_name in copier_arg_names:
                        var = context.vars[arg_name]
                        calldata_offset = calldata_offset_map[arg_name]
                        if sig.private:
                            _offset = calldata_offset
                            if isinstance(var.typ, ByteArrayType):
                                _size = 32
                                dynamics.append(var.pos)
                            else:
                                _size = var.size * 32
                            default_copiers.append(get_arg_copier(sig=sig, memory_dest=var.pos, total_size=_size, offset=_offset))
                        else:
                            # Add clampers.
                            default_copiers.append(make_clamper(calldata_offset - 4, var.pos, var.typ))
                            # Add copying code.
                            if isinstance(var.typ, ByteArrayType):
                                _offset = ['add', 4, ['calldataload', calldata_offset]]
                            else:
                                _offset = calldata_offset
                            default_copiers.append(get_arg_copier(sig=sig, memory_dest=var.pos, total_size=var.size * 32, offset=_offset))

                    # Unpack byte array if necessary.
                    if dynamics:
                        i_placeholder = context.new_placeholder(typ=BaseType('uint256'))
                        for idx, var_pos in enumerate(dynamics):
                            ident = 'unpack_default_sig_dyn_%d_arg%d' % (default_sig.method_id, idx)
                            default_copiers.append(
                                make_unpacker(ident=ident, i_placeholder=i_placeholder, begin_pos=var_pos)
                            )
                    default_copiers.append(0)  # for over arching seq, POP

                sig_chain.append([
                    'if', sig_compare,
                    ['seq',
                        private_label,
                        LLLnode.from_list(['mstore', context.callback_ptr, 'pass'], annotation='pop callback pointer', pos=getpos(code)) if sig.private else ['pass'],
                        ['seq'] + set_defaults if set_defaults else ['pass'],
                        ['seq_unchecked'] + default_copiers if default_copiers else ['pass'],
                        ['goto', _post_callback_ptr if sig.private else function_routine]]
                ])

            # With private functions all variable loading occurs in the default
            # function sub routine.
            if sig.private:
                _clampers = [['label', _post_callback_ptr]]
            else:
                _clampers = clampers

            # Function with default parameters.
            o = LLLnode.from_list(
                ['seq',
                    sig_chain,
                    ['if', 0,  # can only be jumped into
                        ['seq',
                            ['label', function_routine] if not sig.private else ['pass'],
                            ['seq'] + _clampers + [parse_body(c, context) for c in code.body] + stop_func]]], typ=None, pos=getpos(code))

        else:
            # Function without default parameters.
            sig_compare, private_label = get_sig_statements(sig, getpos(code))
            o = LLLnode.from_list(
                ['if',
                    sig_compare,
                    ['seq'] + [private_label] + clampers + [parse_body(c, context) for c in code.body] + stop_func], typ=None, pos=getpos(code))

    # Check for at leasts one return statement if necessary.
    if context.return_type and context.function_return_count == 0:
        raise FunctionDeclarationException(
            "Missing return statement in function '%s' " % sig.name, code
        )

    o.context = context
    o.total_gas = o.gas + calc_mem_gas(o.context.next_mem)
    o.func_name = sig.name
    return o


# Parse a piece of code
def parse_body(code, context):
    if not isinstance(code, list):
        return parse_stmt(code, context)
    o = []
    for stmt in code:
        lll = parse_stmt(stmt, context)
        o.append(lll)
    return LLLnode.from_list(['seq'] + o, pos=getpos(code[0]) if code else None)


def external_contract_call(node, context, contract_name, contract_address, pos, value=None, gas=None):
    if value is None:
        value = 0
    if gas is None:
        gas = 'gas'
    if contract_name not in context.sigs:
        raise VariableDeclarationException("Contract not declared yet: %s" % contract_name)
    method_name = node.func.attr
    if method_name not in context.sigs[contract_name]:
        raise FunctionDeclarationException("Function not declared yet: %s (reminder: "
                                                    "function must be declared in the correct contract)" % method_name, pos)
    sig = context.sigs[contract_name][method_name]
    inargs, inargsize, _ = pack_arguments(sig, [parse_expr(arg, context) for arg in node.args], context, pos=pos)
    output_placeholder, output_size, returner = get_external_contract_call_output(sig, context)
    sub = ['seq', ['assert', ['extcodesize', contract_address]],
                    ['assert', ['ne', 'address', contract_address]]]
    if context.is_constant or sig.const:
        sub.append(['assert', ['staticcall', gas, contract_address, inargs, inargsize, output_placeholder, output_size]])
    else:
        sub.append(['assert', ['call', gas, contract_address, value, inargs, inargsize, output_placeholder, output_size]])
    sub.extend(returner)
    o = LLLnode.from_list(sub, typ=sig.output_type, location='memory', pos=getpos(node))
    return o


def get_external_contract_call_output(sig, context):
    if not sig.output_type:
        return 0, 0, []
    output_placeholder = context.new_placeholder(typ=sig.output_type)
    output_size = get_size_of_type(sig.output_type) * 32
    if isinstance(sig.output_type, BaseType):
        returner = [0, output_placeholder]
    elif isinstance(sig.output_type, ByteArrayType):
        returner = [0, output_placeholder + 32]
    else:
        raise TypeMismatchException("Invalid output type: %s" % sig.output_type)
    return output_placeholder, output_size, returner


# Parse an expression
def parse_expr(expr, context):
    return Expr(expr, context).lll_node


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


def pack_logging_topics(event_id, args, expected_topics, context, pos):
    topics = [event_id]
    for pos, expected_topic in enumerate(expected_topics):
        expected_type = expected_topic.typ
        arg = args[pos]
        value = parse_expr(arg, context)
        arg_type = value.typ

        if isinstance(arg_type, ByteArrayType) and isinstance(expected_type, ByteArrayType):
            if arg_type.maxlen > expected_type.maxlen:
                raise TypeMismatchException("Topic input bytes are too big: %r %r" % (arg_type, expected_type), pos)
            if isinstance(arg, ast.Str):
                bytez, bytez_length = string_to_bytes(arg.s)
                if len(bytez) > 32:
                    raise InvalidLiteralException("Can only log a maximum of 32 bytes at a time.", pos)
                topics.append(bytes_to_int(bytez + b'\x00' * (32 - bytez_length)))
            else:
                if value.location == "memory":
                    size = ['mload', value]
                elif value.location == "storage":
                    size = ['sload', ['sha3_32', value]]
                topics.append(byte_array_to_num(value, arg, 'uint256', size))
        else:
            value = unwrap_location(value)
            value = base_type_conversion(value, arg_type, expected_type, pos=pos)
            topics.append(value)

    return topics


def pack_args_by_32(holder, maxlen, arg, typ, context, placeholder,
                    dynamic_offset_counter=None, datamem_start=None, zero_pad_i=None, pos=None):
    """
    Copy necessary variables to pre-allocated memory section.

    :param holder: Complete holder for all args
    :param maxlen: Total length in bytes of the full arg section (static + dynamic).
    :param arg: Current arg to pack
    :param context: Context of arg
    :param placeholder: Static placeholder for static argument part.
    :param dynamic_offset_counter: position counter stored in static args.
    :param dynamic_placeholder: pointer to current position in memory to write dynamic values to.
    :param datamem_start: position where the whole datemem section starts.
    """

    if isinstance(typ, BaseType):
        value = parse_expr(arg, context)
        value = base_type_conversion(value, value.typ, typ, pos)
        holder.append(LLLnode.from_list(['mstore', placeholder, value], typ=typ, location='memory'))
    elif isinstance(typ, ByteArrayType):
        bytez = b''

        source_expr = Expr(arg, context)
        if isinstance(arg, ast.Str):
            if len(arg.s) > typ.maxlen:
                raise TypeMismatchException("Data input bytes are to big: %r %r" % (len(arg.s), typ), pos)
            for c in arg.s:
                if ord(c) >= 256:
                    raise InvalidLiteralException("Cannot insert special character %r into byte array" % c, pos)
                bytez += bytes([ord(c)])

            holder.append(source_expr.lll_node)

        # Set static offset, in arg slot.
        holder.append(LLLnode.from_list(['mstore', placeholder, ['mload', dynamic_offset_counter]]))
        # Get the biginning to write the ByteArray to.
        dest_placeholder = LLLnode.from_list(
            ['add', datamem_start, ['mload', dynamic_offset_counter]],
            typ=typ, location='memory', annotation="pack_args_by_32:dest_placeholder")
        copier = make_byte_array_copier(dest_placeholder, source_expr.lll_node, pos=pos)
        holder.append(copier)
        # Add zero padding.
        new_maxlen = ceil32(source_expr.lll_node.typ.maxlen)

        holder.append(
            ['with', '_bytearray_loc', dest_placeholder,
                ['seq',
                    ['repeat', zero_pad_i, ['mload', '_bytearray_loc'], new_maxlen,
                        ['seq',
                            ['if', ['ge', ['mload', zero_pad_i], new_maxlen], 'break'],  # stay within allocated bounds
                            ['mstore8', ['add', ['add', '_bytearray_loc', 32], ['mload', zero_pad_i]], 0]]]]]
        )
        # Increment offset counter.
        increment_counter = LLLnode.from_list(
            ['mstore', dynamic_offset_counter,
                ['add', ['add', ['mload', dynamic_offset_counter], ['ceil32', ['mload', dest_placeholder]]], 32]]
        )
        holder.append(increment_counter)
    elif isinstance(typ, ListType):
        maxlen += (typ.count - 1) * 32
        typ = typ.subtype

        def check_list_type_match(provided):  # Check list types match.
            if provided != typ:
                raise TypeMismatchException(
                    "Log list type '%s' does not match provided, expected '%s'" % (provided, typ)
                )

        # List from storage
        if isinstance(arg, ast.Attribute) and arg.value.id == 'self':
            stor_list = context.globals[arg.attr]
            check_list_type_match(stor_list.typ.subtype)
            size = stor_list.typ.count
            for offset in range(0, size):
                arg2 = LLLnode.from_list(['sload', ['add', ['sha3_32', Expr(arg, context).lll_node], offset]],
                                         typ=typ)
                p_holder = context.new_placeholder(BaseType(32)) if offset > 0 else placeholder
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, p_holder, pos=pos)
        # List from variable.
        elif isinstance(arg, ast.Name):
            size = context.vars[arg.id].size
            pos = context.vars[arg.id].pos
            check_list_type_match(context.vars[arg.id].typ.subtype)
            for i in range(0, size):
                offset = 32 * i
                arg2 = LLLnode.from_list(pos + offset, typ=typ, location='memory')
                p_holder = context.new_placeholder(BaseType(32)) if i > 0 else placeholder
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, p_holder, pos=pos)
        # is list literal.
        else:
            holder, maxlen = pack_args_by_32(holder, maxlen, arg.elts[0], typ, context, placeholder, pos=pos)
            for j, arg2 in enumerate(arg.elts[1:]):
                holder, maxlen = pack_args_by_32(holder, maxlen, arg2, typ, context, context.new_placeholder(BaseType(32)), pos=pos)

    return holder, maxlen


# Pack logging data arguments
def pack_logging_data(expected_data, args, context, pos):
    # Checks to see if there's any data
    if not args:
        return ['seq'], 0, None, 0
    holder = ['seq']
    maxlen = len(args) * 32  # total size of all packed args (upper limit)

    requires_dynamic_offset = any([isinstance(data.typ, ByteArrayType) for data in expected_data])
    if requires_dynamic_offset:
        zero_pad_i = context.new_placeholder(BaseType('uint256'))  # Iterator used to zero pad memory.
        dynamic_offset_counter = context.new_placeholder(BaseType(32))
        dynamic_placeholder = context.new_placeholder(BaseType(32))
    else:
        dynamic_offset_counter = None
        zero_pad_i = None

    # Populate static placeholders.
    placeholder_map = {}
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        placeholder = context.new_placeholder(BaseType(32))
        placeholder_map[i] = placeholder
        if not isinstance(typ, ByteArrayType):
            holder, maxlen = pack_args_by_32(holder, maxlen, arg, typ, context, placeholder, zero_pad_i=zero_pad_i, pos=pos)

    # Dynamic position starts right after the static args.
    if requires_dynamic_offset:
        holder.append(LLLnode.from_list(['mstore', dynamic_offset_counter, maxlen]))

    # Calculate maximum dynamic offset placeholders, used for gas estimation.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        if isinstance(typ, ByteArrayType):
            maxlen += 32 + ceil32(typ.maxlen)

    if requires_dynamic_offset:
        datamem_start = dynamic_placeholder + 32
    else:
        datamem_start = placeholder_map[0]

    # Copy necessary data into allocated dynamic section.
    for i, (arg, data) in enumerate(zip(args, expected_data)):
        typ = data.typ
        if isinstance(typ, ByteArrayType):
            pack_args_by_32(
                holder=holder,
                maxlen=maxlen,
                arg=arg,
                typ=typ,
                context=context,
                placeholder=placeholder_map[i],
                datamem_start=datamem_start,
                dynamic_offset_counter=dynamic_offset_counter,
                zero_pad_i=zero_pad_i,
                pos=pos
            )

    return holder, maxlen, dynamic_offset_counter, datamem_start


def parse_to_lll(kode, runtime_only=False):
    code = parse(kode)
    return parse_tree_to_lll(code, kode, runtime_only=runtime_only)
