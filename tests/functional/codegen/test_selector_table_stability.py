from vyper.codegen.jumptable_utils import generate_sparse_jumptable_buckets
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings


def test_dense_jumptable_stability():
    function_names = [f"foo{i}" for i in range(30)]

    code = "\n".join(f"@external\ndef {name}():\n  pass" for name in function_names)

    output = compile_code(
        code, output_formats=["asm"], settings=Settings(optimize=OptimizationLevel.CODESIZE)
    )

    # test that the selector table data is stable across different runs
    # (xdist should provide different PYTHONHASHSEEDs).
    expected_asm = """{ DATA BUCKET_HEADERS b\'\\x0bB\' LABEL bucket_0 b\'\\n\' b\'+\\x8d\' LABEL bucket_1 b\'\\x0c\' b\'\\x00\\x85\' LABEL bucket_2 b\'\\x08\' } { DATA bucket_1 b\'\\xd8\\xee\\xa1\\xe8\' LABEL external 6 foo6()3639517672 b\'\\x05\' b\'\\xd2\\x9e\\xe0\\xf9\' LABEL external 0 foo0()3533627641 b\'\\x05\' b\'\\x05\\xf1\\xe0_\' LABEL external 2 foo2()99737695 b\'\\x05\' b\'\\x91\\t\\xb4{\' LABEL external 23 foo23()2433332347 b\'\\x05\' b\'np3\\x7f\' LABEL external 11 foo11()1852846975 b\'\\x05\' b\'&\\xf5\\x96\\xf9\' LABEL external 13 foo13()653629177 b\'\\x05\' b\'\\x04ga\\xeb\' LABEL external 14 foo14()73884139 b\'\\x05\' b\'\\x89\\x06\\xad\\xc6\' LABEL external 17 foo17()2298916294 b\'\\x05\' b\'\\xe4%\\xac\\xd1\' LABEL external 4 foo4()3827674321 b\'\\x05\' b\'yj\\x01\\xac\' LABEL external 7 foo7()2036990380 b\'\\x05\' b\'\\xf1\\xe6K\\xe5\' LABEL external 29 foo29()4058401765 b\'\\x05\' b\'\\xd2\\x89X\\xb8\' LABEL external 3 foo3()3532216504 b\'\\x05\' } { DATA bucket_2 b\'\\x06p\\xffj\' LABEL external 25 foo25()108068714 b\'\\x05\' b\'\\x964\\x99I\' LABEL external 24 foo24()2520029513 b\'\\x05\' b\'s\\x81\\xe7\\xc1\' LABEL external 10 foo10()1937893313 b\'\\x05\' b\'\\x85\\xad\\xc11\' LABEL external 28 foo28()2242756913 b\'\\x05\' b\'\\xfa"\\xb1\\xed\' LABEL external 5 foo5()4196577773 b\'\\x05\' b\'A\\xe7[\\x05\' LABEL external 22 foo22()1105681157 b\'\\x05\' b\'\\xd3\\x89U\\xe8\' LABEL external 1 foo1()3548993000 b\'\\x05\' b\'hL\\xf8\\xf3\' LABEL external 20 foo20()1749874931 b\'\\x05\' } { DATA bucket_0 b\'\\xee\\xd9\\x1d\\xe3\' LABEL external 9 foo9()4007206371 b\'\\x05\' b\'a\\xbc\\x1ch\' LABEL external 16 foo16()1639717992 b\'\\x05\' b\'\\xd3*\\xa7\\x0c\' LABEL external 21 foo21()3542787852 b\'\\x05\' b\'\\x18iG\\xd9\' LABEL external 19 foo19()409552857 b\'\\x05\' b\'\\n\\xf1\\xf9\\x7f\' LABEL external 18 foo18()183630207 b\'\\x05\' b\')\\xda\\xd7`\' LABEL external 27 foo27()702207840 b\'\\x05\' b\'2\\xf6\\xaa\\xda\' LABEL external 12 foo12()855026394 b\'\\x05\' b\'\\xbe\\xb5\\x05\\xf5\' LABEL external 15 foo15()3199534581 b\'\\x05\' b\'\\xfc\\xa7_\\xe6\' LABEL external 8 foo8()4238827494 b\'\\x05\' b\'\\x1b\\x12C8\' LABEL external 26 foo26()454181688 b\'\\x05\' } }"""  # noqa: E501, FS003
    assert expected_asm in output["asm"]


def test_sparse_jumptable_stability():
    function_names = [f"foo{i}()" for i in range(30)]

    # sparse jumptable is not as complicated in assembly.
    # here just test the data structure is stable

    n_buckets, buckets = generate_sparse_jumptable_buckets(function_names)
    assert n_buckets == 33

    # the buckets sorted by id are what go into the IR, check equality against
    # expected:
    assert sorted(buckets.items()) == [
        (0, [4238827494, 1639717992]),
        (1, [1852846975]),
        (2, [1749874931]),
        (3, [4007206371]),
        (4, [2298916294]),
        (7, [2036990380]),
        (10, [3639517672, 73884139]),
        (12, [3199534581]),
        (13, [99737695]),
        (14, [3548993000, 4196577773]),
        (15, [454181688, 702207840]),
        (16, [3533627641]),
        (17, [108068714]),
        (20, [1105681157]),
        (21, [409552857, 3542787852]),
        (22, [4058401765]),
        (23, [2520029513, 2242756913]),
        (24, [855026394, 183630207]),
        (25, [3532216504, 653629177]),
        (26, [1937893313]),
        (28, [2433332347]),
        (31, [3827674321]),
    ]
