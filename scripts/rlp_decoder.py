from viper import optimizer, compile_lll
from viper.parser.parser_utils import LLLnode
from viper.utils import MemoryPositions

def call_data_char(position):
    return ['div', ['calldataload', position], 2**248]

def call_data_bytes_as_int(x, b):
    return ['seq', ['mstore', sub(32, b), ['calldataload', x]], 
            ['mload', 0]]

def add(x, y):
    return ['add', x, y]

def sub(x, y):
    return ['sub', x, y]

loop_memory_position = 544
positions = 64
data = 1088
position_index = 2476
data_pos = 2508
c = 2540
i = 2572
L = 2604
position_offset = 2304

rlp_decoder_lll = LLLnode.from_list(['seq', 
    ['return', [0],
        ['lll',
            ['seq',
                ['mstore', position_index, 0],
                ['mstore', data_pos, 0],
                ['mstore', c, call_data_char(0)],
                ['mstore', i, 0],
                ['mstore', position_offset, 0],
                ['assert', ['ge', ['mload', c], 192]], # Must be a list
                ['if', ['lt', ['mload', c], 248], # if c < 248:
                    ['seq',
                        ['assert', ['eq', ['calldatasize'], sub(['mload', c], 191)]], # assert ~calldatasize() == (c - 191)
                        ['mstore', i, 1] # i = 1
                    ],
                    ['seq',
                        ['assert', ['eq', ['calldatasize'], add(sub(['mload', c], 246), call_data_bytes_as_int(1, sub(['mload', c], 247)))]], # assert ~calldatasize() == (c - 246) + calldatabytes_as_int(1, c - 247)
                        ['mstore', i, sub(['mload', c], 246)] # i = c - 246
                    ],
                ],
                # Main loop
                # Here, we simultaneously build up data in two places:
                # (i) starting from memory index 64, a list of 32-byte numbers
                #     representing the start positions of each value
                # (ii) starting from memory index 1088, the values, in format
                #     <length as 32 byte int> <value>, packed one after the other
                ['repeat', loop_memory_position, 1, 100,
                    ['seq',
                        ['if', ['ge', ['mload', i], 'calldatasize'], 'break'],
                        ['mstore', c, call_data_char(['mload', i])],
                        ['mstore', add(positions, ['mul', ['mload', position_index], 32]), ['mload', data_pos]],
                        ['mstore', position_index, add(['mload', position_index], 1)],
                        ['if', ['lt', ['mload', c], 128],
                            ['seq',
                                ['mstore', add(data, ['mload', data_pos]), 1],
                                ['calldatacopy', add(data + 32, ['mload', data_pos]), ['mload', i], 1],
                                ['mstore', i, add(['mload', i], 1)],
                                ['mstore', data_pos, add(['mload', data_pos], 33)]
                            ],
                            ['if', ['lt', ['mload', c], 184], 
                                ['seq',
                                    ['mstore', add(data, ['mload', data_pos]), sub(['mload', c], 128)],
                                    ['calldatacopy', add(data + 32, ['mload', data_pos]), add(['mload', i], 1), sub(['mload', c], 128)],
                                    ['if', ['eq', ['mload', c], 129],
                                        ['assert', ['ge', call_data_char(add(['mload', i],1)), 128]]
                                    ],
                                    ['mstore', i, add(['mload', i], sub(['mload', c], 127))],
                                    ['mstore', data_pos, add(['mload', data_pos], sub(['mload', c], 96))]
                                ],
                                ['if', ['lt', ['mload', c], 192],
                                    ['seq',
                                        ['mstore', L, call_data_bytes_as_int(add(['mload', i], 1), sub(['mload', c], 183))],
                                        ['assert', ['mul', call_data_char(add(['mload', i], 1)), ['ge', ['mload', L], 56]]],
                                        ['mstore', add(data, ['mload', data_pos]), ['mload', L]],
                                        ['calldatacopy', add(data + 32, ['mload', data_pos]), add(['mload', i], sub(['mload', c], 182)), ['mload', L]],
                                        ['mstore', i, add(add(['mload', i], sub(['mload', c], 182)), ['mload', L])],
                                        ['mstore', data_pos, add(['mload', data_pos], add(['mload', L], 32))]
                                    ],
                                    ['invalid']
                                ]
                            ]
                        ],
                    ]
                ],
                ['assert', ['le', ['mload', position_index], 31]],
                ['mstore', position_offset, add(['mul', ['mload', position_index], 32], 32)],
                ['mstore', i, sub(['mload', position_offset], 32)],
                ['repeat', loop_memory_position, 1, 100,
                    ['seq',
                        ['if', ['slt', ['mload', i], 0], 'break'],
                        ['mstore', add(sub(data, ['mload', position_offset]), ['mload', i]), add(['mload', add(positions, ['mload', i])], ['mload', position_offset])],
                        # ~mstore(data - positionOffset + i, ~mload(positions + i) + positionOffset)
                        ['mstore', i, sub(['mload', i], 32)],
                    ]
                ],
                ['mstore', sub(data, 32), add(['mload', position_offset], ['mload', data_pos])],
                ['return', sub(data, ['mload', position_offset]), add(['mload', position_offset], ['mload', data_pos])]
            ],
        [0]]
    ]])

rlp_decoder_lll = optimizer.optimize(rlp_decoder_lll)
rlp_decoder_bytes = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(rlp_decoder_lll))