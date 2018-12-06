# Module for codegen. Currently most codegen lives in
# parser/parser_utils.py and can slowly be migrated here as
# type-checking code gets factored out.

from vyper.exceptions import (
    TypeMismatchException,
)
from vyper.types import (
    BaseType,
    ByteArrayType,
    TupleLike,
)
from vyper.parser.parser_utils import (
    getpos,
    LLLnode,
    make_setter,
    add_variable_offset,
    get_size_of_type
)


def zero_pad(bytez_placeholder, maxlen, context):
    zero_padder = LLLnode.from_list(['pass'])
    if maxlen > 0:
        zero_pad_i = context.new_placeholder(BaseType('uint256'))  # Iterator used to zero pad memory.
        zero_padder = LLLnode.from_list(
            ['repeat', zero_pad_i, ['mload', bytez_placeholder], maxlen,
                ['seq',
                    ['if', ['gt', ['mload', zero_pad_i], maxlen], 'break'],  # stay within allocated bounds
                    ['mstore8', ['add', ['add', 32, bytez_placeholder], ['mload', zero_pad_i]], 0]]],
            annotation="Zero pad"
        )
    return zero_padder


# Generate return code for stmt
def make_return_stmt(stmt, context, begin_pos, _size, loop_memory_position=None):
    if context.is_private:
        if loop_memory_position is None:
            loop_memory_position = context.new_placeholder(typ=BaseType('uint256'))

        # Make label for stack push loop.
        label_id = '_'.join([str(x) for x in (context.method_id, stmt.lineno, stmt.col_offset)])
        exit_label = 'make_return_loop_exit_%s' % label_id
        start_label = 'make_return_loop_start_%s' % label_id

        # Push prepared data onto the stack,
        # in reverse order so it can be popped of in order.
        if _size == 0:
            mloads = []
        elif isinstance(begin_pos, int) and isinstance(_size, int):
            # static values, unroll the mloads instead.
            mloads = [
                ['mload', pos] for pos in range(begin_pos, _size, 32)
            ]
            return ['seq_unchecked'] + mloads + [['jump', ['mload', context.callback_ptr]]]
        else:
            mloads = [
                'seq_unchecked',
                ['mstore', loop_memory_position, _size],
                ['label', start_label],
                ['if',
                    ['le', ['mload', loop_memory_position], 0], ['goto', exit_label]],  # exit loop / break.
                ['mload', ['add', begin_pos, ['sub', ['mload', loop_memory_position], 32]]],  # push onto stack
                ['mstore', loop_memory_position, ['sub', ['mload', loop_memory_position], 32]],  # decrement i by 32.
                ['goto', start_label],
                ['label', exit_label]
            ]
            return ['seq_unchecked'] + [mloads] + [['jump', ['mload', context.callback_ptr]]]
    else:
        return ['return', begin_pos, _size]


# Generate code for returning a tuple or struct.
def gen_tuple_return(stmt, context, sub):
    # Is from a call expression.
    if sub.args and len(sub.args[0].args) > 0 and sub.args[0].args[0].value == 'call':  # self-call to public.
        mem_pos = sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        return LLLnode.from_list(['return', mem_pos, mem_size], typ=sub.typ)

    elif (sub.annotation and 'Internal Call' in sub.annotation):
        mem_pos = sub.args[-1].value if sub.value == 'seq_unchecked' else sub.args[0].args[-1]
        mem_size = get_size_of_type(sub.typ) * 32
        # Add zero padder if bytes are present in output.
        zero_padder = ['pass']
        byte_arrays = [(i, x) for i, x in enumerate(sub.typ.get_tuple_members()) if isinstance(x, ByteArrayType)]
        if byte_arrays:
            i, x = byte_arrays[-1]
            zero_padder = zero_pad(bytez_placeholder=['add', mem_pos, ['mload', mem_pos + i * 32]], maxlen=x.maxlen, context=context)
        return LLLnode.from_list(
            ['seq'] + [sub] + [zero_padder] + [make_return_stmt(stmt, context, mem_pos, mem_size)
        ], typ=sub.typ, pos=getpos(stmt), valency=0)

    subs = []
    # Pre-allocate loop_memory_position if required for private function returning.
    loop_memory_position = context.new_placeholder(typ=BaseType('uint256')) if context.is_private else None
    # Allocate dynamic off set counter, to keep track of the total packed dynamic data size.
    dynamic_offset_counter_placeholder = context.new_placeholder(typ=BaseType('uint256'))
    dynamic_offset_counter = LLLnode(
        dynamic_offset_counter_placeholder, typ=None, annotation="dynamic_offset_counter"  # dynamic offset position counter.
    )
    new_sub = LLLnode.from_list(
        context.new_placeholder(typ=BaseType('uint256')), typ=context.return_type, location='memory', annotation='new_sub'
    )
    left_token = LLLnode.from_list('_loc', typ=new_sub.typ, location="memory")

    def get_dynamic_offset_value():
        # Get value of dynamic offset counter.
        return ['mload', dynamic_offset_counter]

    def increment_dynamic_offset(dynamic_spot):
        # Increment dyanmic offset counter in memory.
        return [
            'mstore', dynamic_offset_counter,
            ['add',
                ['add', ['ceil32', ['mload', dynamic_spot]], 32],
                ['mload', dynamic_offset_counter]]
        ]

    if sub.typ.is_literal:
        keyz = list(range(len(sub.typ.members)))
    else:
        keyz = [(k, v) for k, v in sub.typ.members.items()]
    dynamic_offset_start = 32 * len(keyz)  # The static list of args end.

    for i, (key, typ) in enumerate(keyz):
        variable_offset = LLLnode.from_list(['add', 32 * i, left_token], typ=typ, annotation='variable_offset')   # variable offset of destination
        if sub.typ.is_literal:
            arg = sub.args[i]
        else:
            arg = add_variable_offset(parent=sub, key=key, pos=getpos(stmt))

        # arg = args[i] if sub.typ.is_literal else add_variable_offset(typ)  # origin arg to copy from
        if isinstance(typ, ByteArrayType):
            # Store offset pointer value.
            subs.append(['mstore', variable_offset, get_dynamic_offset_value()])

            # Store dynamic data, from offset pointer onwards.
            dynamic_spot = LLLnode.from_list(['add', left_token, get_dynamic_offset_value()], location="memory", typ=typ, annotation='dynamic_spot')
            subs.append(make_setter(dynamic_spot, arg, location="memory", pos=getpos(stmt)))
            subs.append(increment_dynamic_offset(dynamic_spot))

        elif isinstance(typ, BaseType):
            subs.append(make_setter(variable_offset, arg, "memory", pos=getpos(stmt)))
        elif isinstance(typ, TupleLike):
            subs.append(gen_tuple_return(stmt, context, arg))
        else:
            # Maybe this should panic because the type error should be
            # caught at an earlier type-checking stage.
            raise TypeMismatchException("Can't return type %s as part of tuple" % arg.typ, stmt)

    setter = LLLnode.from_list(
        ['seq',
            ['mstore', dynamic_offset_counter, dynamic_offset_start],
            ['with', '_loc', new_sub, ['seq'] + subs]],
        typ=None
    )

    return LLLnode.from_list(
        ['seq',
            setter,
            make_return_stmt(stmt, context, new_sub, get_dynamic_offset_value(), loop_memory_position)],
        typ=None, pos=getpos(stmt), valency=0
    )
