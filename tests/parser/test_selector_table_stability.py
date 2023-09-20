from vyper.codegen.jumptable_utils import generate_sparse_jumptable_buckets
from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings


def test_dense_jumptable_stability():
    function_names = [f"foo{i}" for i in range(30)]

    code = "\n".join(f"@external\ndef {name}():\n  pass" for name in function_names)

    output = compile_code(code, ["asm"], settings=Settings(optimize=OptimizationLevel.CODESIZE))

    # test that the selector table data is stable across different runs
    # (tox should provide different PYTHONHASHSEEDs).
    expected_asm = """{ DATA _sym_BUCKET_HEADERS b'\\x0bB' _sym_bucket_0 b'\\n' b'+\\x8d' _sym_bucket_1 b'\\x0c' b'\\x00\\x85' _sym_bucket_2 b'\\x08' } { DATA _sym_bucket_1 b'\\xd8\\xee\\xa1\\xe8' _sym_external_foo6___3639517672 b'\\x05' b'\\xd2\\x9e\\xe0\\xf9' _sym_external_foo0___3533627641 b'\\x05' b'\\x05\\xf1\\xe0_' _sym_external_foo2___99737695 b'\\x05' b'\\x91\\t\\xb4{' _sym_external_foo23___2433332347 b'\\x05' b'np3\\x7f' _sym_external_foo11___1852846975 b'\\x05' b'&\\xf5\\x96\\xf9' _sym_external_foo13___653629177 b'\\x05' b'\\x04ga\\xeb' _sym_external_foo14___73884139 b'\\x05' b'\\x89\\x06\\xad\\xc6' _sym_external_foo17___2298916294 b'\\x05' b'\\xe4%\\xac\\xd1' _sym_external_foo4___3827674321 b'\\x05' b'yj\\x01\\xac' _sym_external_foo7___2036990380 b'\\x05' b'\\xf1\\xe6K\\xe5' _sym_external_foo29___4058401765 b'\\x05' b'\\xd2\\x89X\\xb8' _sym_external_foo3___3532216504 b'\\x05' } { DATA _sym_bucket_2 b'\\x06p\\xffj' _sym_external_foo25___108068714 b'\\x05' b'\\x964\\x99I' _sym_external_foo24___2520029513 b'\\x05' b's\\x81\\xe7\\xc1' _sym_external_foo10___1937893313 b'\\x05' b'\\x85\\xad\\xc11' _sym_external_foo28___2242756913 b'\\x05' b'\\xfa"\\xb1\\xed' _sym_external_foo5___4196577773 b'\\x05' b'A\\xe7[\\x05' _sym_external_foo22___1105681157 b'\\x05' b'\\xd3\\x89U\\xe8' _sym_external_foo1___3548993000 b'\\x05' b'hL\\xf8\\xf3' _sym_external_foo20___1749874931 b'\\x05' } { DATA _sym_bucket_0 b'\\xee\\xd9\\x1d\\xe3' _sym_external_foo9___4007206371 b'\\x05' b'a\\xbc\\x1ch' _sym_external_foo16___1639717992 b'\\x05' b'\\xd3*\\xa7\\x0c' _sym_external_foo21___3542787852 b'\\x05' b'\\x18iG\\xd9' _sym_external_foo19___409552857 b'\\x05' b'\\n\\xf1\\xf9\\x7f' _sym_external_foo18___183630207 b'\\x05' b')\\xda\\xd7`' _sym_external_foo27___702207840 b'\\x05' b'2\\xf6\\xaa\\xda' _sym_external_foo12___855026394 b'\\x05' b'\\xbe\\xb5\\x05\\xf5' _sym_external_foo15___3199534581 b'\\x05' b'\\xfc\\xa7_\\xe6' _sym_external_foo8___4238827494 b'\\x05' b'\\x1b\\x12C8' _sym_external_foo26___454181688 b'\\x05' } }"""  # noqa: E501
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
