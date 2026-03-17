from vyper.codegen.jumptable_utils import generate_sparse_jumptable_buckets
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings


def test_dense_jumptable_stability():
    function_names = [f"foo{i}" for i in range(30)]

    code = "\n".join(f"@external\ndef {name}():\n  pass" for name in function_names)

    output = compile_code(
        code, output_formats=["asm_runtime"], settings=Settings(optimize=OptimizationLevel.CODESIZE)
    )

    # test that the selector table data is stable across different runs
    # (xdist should provide different PYTHONHASHSEEDs).
    expected_asm = """DATA BUCKET_HEADERS:\n    DATABYTES 0b42\n    DATALABEL bucket_0\n    DATABYTES 0a\n    DATABYTES 2b8d\n    DATALABEL bucket_1\n    DATABYTES 0c\n    DATABYTES 0085\n    DATALABEL bucket_2\n    DATABYTES 08\n\nDATA bucket_1:\n    DATABYTES d8eea1e8\n    DATALABEL external 6 foo6()3639517672\n    DATABYTES 05\n    DATABYTES d29ee0f9\n    DATALABEL external 0 foo0()3533627641\n    DATABYTES 05\n    DATABYTES 05f1e05f\n    DATALABEL external 2 foo2()99737695\n    DATABYTES 05\n    DATABYTES 9109b47b\n    DATALABEL external 23 foo23()2433332347\n    DATABYTES 05\n    DATABYTES 6e70337f\n    DATALABEL external 11 foo11()1852846975\n    DATABYTES 05\n    DATABYTES 26f596f9\n    DATALABEL external 13 foo13()653629177\n    DATABYTES 05\n    DATABYTES 046761eb\n    DATALABEL external 14 foo14()73884139\n    DATABYTES 05\n    DATABYTES 8906adc6\n    DATALABEL external 17 foo17()2298916294\n    DATABYTES 05\n    DATABYTES e425acd1\n    DATALABEL external 4 foo4()3827674321\n    DATABYTES 05\n    DATABYTES 796a01ac\n    DATALABEL external 7 foo7()2036990380\n    DATABYTES 05\n    DATABYTES f1e64be5\n    DATALABEL external 29 foo29()4058401765\n    DATABYTES 05\n    DATABYTES d28958b8\n    DATALABEL external 3 foo3()3532216504\n    DATABYTES 05\n\nDATA bucket_2:\n    DATABYTES 0670ff6a\n    DATALABEL external 25 foo25()108068714\n    DATABYTES 05\n    DATABYTES 96349949\n    DATALABEL external 24 foo24()2520029513\n    DATABYTES 05\n    DATABYTES 7381e7c1\n    DATALABEL external 10 foo10()1937893313\n    DATABYTES 05\n    DATABYTES 85adc131\n    DATALABEL external 28 foo28()2242756913\n    DATABYTES 05\n    DATABYTES fa22b1ed\n    DATALABEL external 5 foo5()4196577773\n    DATABYTES 05\n    DATABYTES 41e75b05\n    DATALABEL external 22 foo22()1105681157\n    DATABYTES 05\n    DATABYTES d38955e8\n    DATALABEL external 1 foo1()3548993000\n    DATABYTES 05\n    DATABYTES 684cf8f3\n    DATALABEL external 20 foo20()1749874931\n    DATABYTES 05\n\nDATA bucket_0:\n    DATABYTES eed91de3\n    DATALABEL external 9 foo9()4007206371\n    DATABYTES 05\n    DATABYTES 61bc1c68\n    DATALABEL external 16 foo16()1639717992\n    DATABYTES 05\n    DATABYTES d32aa70c\n    DATALABEL external 21 foo21()3542787852\n    DATABYTES 05\n    DATABYTES 186947d9\n    DATALABEL external 19 foo19()409552857\n    DATABYTES 05\n    DATABYTES 0af1f97f\n    DATALABEL external 18 foo18()183630207\n    DATABYTES 05\n    DATABYTES 29dad760\n    DATALABEL external 27 foo27()702207840\n    DATABYTES 05\n    DATABYTES 32f6aada\n    DATALABEL external 12 foo12()855026394\n    DATABYTES 05\n    DATABYTES beb505f5\n    DATALABEL external 15 foo15()3199534581\n    DATABYTES 05\n    DATABYTES fca75fe6\n    DATALABEL external 8 foo8()4238827494\n    DATABYTES 05\n    DATABYTES 1b124338\n    DATALABEL external 26 foo26()454181688\n    DATABYTES 05"""  # noqa: E501

    assert expected_asm in output["asm_runtime"]


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
