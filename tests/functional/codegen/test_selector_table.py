import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

import vyper.utils as utils
from vyper.codegen.jumptable_utils import (
    generate_dense_jumptable_info,
    generate_sparse_jumptable_buckets,
)
from vyper.compiler.settings import OptimizationLevel


def test_dense_selector_table_empty_buckets(get_contract):
    # some special combination of selectors which can result in
    # some empty bucket being returned from _mk_buckets (that is,
    # len(_mk_buckets(..., n_buckets)) != n_buckets
    code = """
@external
def aX61QLPWF()->uint256:
    return 1
@external
def aQHG0P2L1()->uint256:
    return 2
@external
def a2G8ME94W()->uint256:
    return 3
@external
def a0GNA21AY()->uint256:
    return 4
@external
def a4U1XA4T5()->uint256:
    return 5
@external
def aAYLMGOBZ()->uint256:
    return 6
@external
def a0KXRLHKE()->uint256:
    return 7
@external
def aDQS32HTR()->uint256:
    return 8
@external
def aP4K6SA3S()->uint256:
    return 9
@external
def aEB94ZP5S()->uint256:
    return 10
@external
def aTOIMN0IM()->uint256:
    return 11
@external
def aXV2N81OW()->uint256:
    return 12
@external
def a66PP6Y5X()->uint256:
    return 13
@external
def a5MWMTEWN()->uint256:
    return 14
@external
def a5ZFST4Z8()->uint256:
    return 15
@external
def aR13VXULX()->uint256:
    return 16
@external
def aWITH917Y()->uint256:
    return 17
@external
def a59NP6C5O()->uint256:
    return 18
@external
def aJ02590EX()->uint256:
    return 19
@external
def aUAXAAUQ8()->uint256:
    return 20
@external
def aWR1XNC6J()->uint256:
    return 21
@external
def aJABKZOKH()->uint256:
    return 22
@external
def aO1TT0RJT()->uint256:
    return 23
@external
def a41442IOK()->uint256:
    return 24
@external
def aMVXV9FHQ()->uint256:
    return 25
@external
def aNN0KJDZM()->uint256:
    return 26
@external
def aOX965047()->uint256:
    return 27
@external
def a575NX2J3()->uint256:
    return 28
@external
def a16EN8O7W()->uint256:
    return 29
@external
def aSZXLFF7O()->uint256:
    return 30
@external
def aQKQCIPH9()->uint256:
    return 31
@external
def aIP8021DL()->uint256:
    return 32
@external
def aQAV0HSHX()->uint256:
    return 33
@external
def aZVPAD745()->uint256:
    return 34
@external
def aJYBSNST4()->uint256:
    return 35
@external
def aQGWC4NYQ()->uint256:
    return 36
@external
def aFMBB9CXJ()->uint256:
    return 37
@external
def aYWM7ZUH1()->uint256:
    return 38
@external
def aJAZONIX1()->uint256:
    return 39
@external
def aQZ1HJK0H()->uint256:
    return 40
@external
def aKIH9LOUB()->uint256:
    return 41
@external
def aF4ZT80XL()->uint256:
    return 42
@external
def aYQD8UKR5()->uint256:
    return 43
@external
def aP6NCCAI4()->uint256:
    return 44
@external
def aY92U2EAZ()->uint256:
    return 45
@external
def aHMQ49D7P()->uint256:
    return 46
@external
def aMC6YX8VF()->uint256:
    return 47
@external
def a734X6YSI()->uint256:
    return 48
@external
def aRXXPNSMU()->uint256:
    return 49
@external
def aL5XKDTGT()->uint256:
    return 50
@external
def a86V1Y18A()->uint256:
    return 51
@external
def aAUM8PL5J()->uint256:
    return 52
@external
def aBAEC1ERZ()->uint256:
    return 53
@external
def a1U1VA3UE()->uint256:
    return 54
@external
def aC9FGVAHC()->uint256:
    return 55
@external
def aWN81WYJ3()->uint256:
    return 56
@external
def a3KK1Y07J()->uint256:
    return 57
@external
def aAZ6P6OSG()->uint256:
    return 58
@external
def aWP5HCIB3()->uint256:
    return 59
@external
def aVEK161C5()->uint256:
    return 60
@external
def aY0Q3O519()->uint256:
    return 61
@external
def aDHHHFIAE()->uint256:
    return 62
@external
def aGSJBCZKQ()->uint256:
    return 63
@external
def aZQQIUDHY()->uint256:
    return 64
@external
def a12O9QDH5()->uint256:
    return 65
@external
def aRQ1178XR()->uint256:
    return 66
@external
def aDT25C832()->uint256:
    return 67
@external
def aCSB01C4E()->uint256:
    return 68
@external
def aYGBPKZSD()->uint256:
    return 69
@external
def aP24N3EJ8()->uint256:
    return 70
@external
def a531Y9X3C()->uint256:
    return 71
@external
def a4727IKVS()->uint256:
    return 72
@external
def a2EX1L2BS()->uint256:
    return 73
@external
def a6145RN68()->uint256:
    return 74
@external
def aDO1ZNX97()->uint256:
    return 75
@external
def a3R28EU6M()->uint256:
    return 76
@external
def a9BFC867L()->uint256:
    return 77
@external
def aPL1MBGYC()->uint256:
    return 78
@external
def aI6H11O48()->uint256:
    return 79
@external
def aX0248DZY()->uint256:
    return 80
@external
def aE4JBUJN4()->uint256:
    return 81
@external
def aXBDB2ZBO()->uint256:
    return 82
@external
def a7O7MYYHL()->uint256:
    return 83
@external
def aERFF4PB6()->uint256:
    return 84
@external
def aJCUBG6TJ()->uint256:
    return 85
@external
def aQ5ELXM0F()->uint256:
    return 86
@external
def aWDT9UQVV()->uint256:
    return 87
@external
def a7UU40DJK()->uint256:
    return 88
@external
def aH01IT5VS()->uint256:
    return 89
@external
def aSKYTZ0FC()->uint256:
    return 90
@external
def aNX5LYRAW()->uint256:
    return 91
@external
def aUDKAOSGG()->uint256:
    return 92
@external
def aZ86YGAAO()->uint256:
    return 93
@external
def aIHWQGKLO()->uint256:
    return 94
@external
def aKIKFLAR9()->uint256:
    return 95
@external
def aCTPE0KRS()->uint256:
    return 96
@external
def aAD75X00P()->uint256:
    return 97
@external
def aDROUEF2F()->uint256:
    return 98
@external
def a8CDIF6YN()->uint256:
    return 99
@external
def aD2X7TM83()->uint256:
    return 100
@external
def a3W5UUB4L()->uint256:
    return 101
@external
def aG4MOBN4B()->uint256:
    return 102
@external
def aPRS0MSG7()->uint256:
    return 103
@external
def aKN3GHBUR()->uint256:
    return 104
@external
def aGE435RHQ()->uint256:
    return 105
@external
def a4E86BNFE()->uint256:
    return 106
@external
def aYDG928YW()->uint256:
    return 107
@external
def a2HFP5GQE()->uint256:
    return 108
@external
def a5DPMVXKA()->uint256:
    return 109
@external
def a3OFVC3DR()->uint256:
    return 110
@external
def aK8F62DAN()->uint256:
    return 111
@external
def aJS9EY3U6()->uint256:
    return 112
@external
def aWW789JQH()->uint256:
    return 113
@external
def a8AJJN3YR()->uint256:
    return 114
@external
def a4D0MUIDU()->uint256:
    return 115
@external
def a35W41JQR()->uint256:
    return 116
@external
def a07DQOI1E()->uint256:
    return 117
@external
def aFT43YNCT()->uint256:
    return 118
@external
def a0E75I8X3()->uint256:
    return 119
@external
def aT6NXIRO4()->uint256:
    return 120
@external
def aXB2UBAKQ()->uint256:
    return 121
@external
def aHWH55NW6()->uint256:
    return 122
@external
def a7TCFE6C2()->uint256:
    return 123
@external
def a8XYAM81I()->uint256:
    return 124
@external
def aHQTQ4YBY()->uint256:
    return 125
@external
def aGCZEHG6Y()->uint256:
    return 126
@external
def a6LJTKIW0()->uint256:
    return 127
@external
def aBDIXTD9S()->uint256:
    return 128
@external
def aCB83G21P()->uint256:
    return 129
@external
def aZC525N4K()->uint256:
    return 130
@external
def a40LC94U6()->uint256:
    return 131
@external
def a8X9TI93D()->uint256:
    return 132
@external
def aGUG9CD8Y()->uint256:
    return 133
@external
def a0LAERVAY()->uint256:
    return 134
@external
def aXQ0UEX19()->uint256:
    return 135
@external
def aKK9C7NE7()->uint256:
    return 136
@external
def aS2APW8UE()->uint256:
    return 137
@external
def a65NT07MM()->uint256:
    return 138
@external
def aGRMT6ZW5()->uint256:
    return 139
@external
def aILR4U1Z()->uint256:
    return 140
    """
    c = get_contract(code)

    assert c.aX61QLPWF() == 1  # will revert if the header section is misaligned


@given(
    n_methods=st.integers(min_value=1, max_value=100),
    seed=st.integers(min_value=0, max_value=2**64 - 1),
)
@pytest.mark.fuzzing
@settings(max_examples=10)
def test_sparse_jumptable_probe_depth(n_methods, seed):
    sigs = [f"foo{i + seed}()" for i in range(n_methods)]
    _, buckets = generate_sparse_jumptable_buckets(sigs)
    bucket_sizes = [len(bucket) for bucket in buckets.values()]

    # generally bucket sizes should be bounded at around 4, but
    # just test that they don't get really out of hand
    assert max(bucket_sizes) <= 8

    # generally mean bucket size should be around 1.6, here just
    # test they don't get really out of hand
    assert sum(bucket_sizes) / len(bucket_sizes) <= 4


@given(
    n_methods=st.integers(min_value=4, max_value=100),
    seed=st.integers(min_value=0, max_value=2**64 - 1),
)
@pytest.mark.fuzzing
@settings(max_examples=10)
def test_dense_jumptable_bucket_size(n_methods, seed):
    sigs = [f"foo{i + seed}()" for i in range(n_methods)]
    n = len(sigs)
    buckets = generate_dense_jumptable_info(sigs)
    n_buckets = len(buckets)

    # generally should be around 14 buckets per 100 methods, here
    # we test they don't get really out of hand
    assert n_buckets / n < 0.4 or n < 10


@st.composite
def generate_methods(draw, max_calldata_bytes):
    max_default_args = draw(st.integers(min_value=0, max_value=4))
    default_fn_mutability = draw(st.sampled_from(["", "@pure", "@view", "@nonpayable", "@payable"]))

    return (
        max_default_args,
        default_fn_mutability,
        draw(
            st.lists(
                st.tuples(
                    # function id:
                    st.integers(min_value=0),
                    # mutability:
                    st.sampled_from(["@pure", "@view", "@nonpayable", "@payable"]),
                    # n calldata words:
                    st.integers(min_value=0, max_value=max_calldata_bytes // 32),
                    # n bytes to strip from calldata
                    st.integers(min_value=1, max_value=4),
                    # n default args
                    st.integers(min_value=0, max_value=max_default_args),
                ),
                unique_by=lambda x: x[0],
                min_size=1,
                max_size=100,
            )
        ),
    )


@pytest.mark.parametrize("opt_level", list(OptimizationLevel))
# dense selector table packing boundaries at 256 and 65336
@pytest.mark.parametrize("max_calldata_bytes", [255, 256, 65336])
@pytest.mark.fuzzing
def test_selector_table_fuzz(max_calldata_bytes, opt_level, w3, get_contract, tx_failed, get_logs):
    def abi_sig(func_id, calldata_words, n_default_args):
        params = [] if not calldata_words else [f"uint256[{calldata_words}]"]
        params.extend(["uint256"] * n_default_args)
        paramstr = ",".join(params)
        return f"foo{func_id}({paramstr})"

    def generate_func_def(func_id, mutability, calldata_words, n_default_args):
        arglist = [] if not calldata_words else [f"x: uint256[{calldata_words}]"]
        for j in range(n_default_args):
            arglist.append(f"x{j}: uint256 = 0")
        args = ", ".join(arglist)
        _log_return = f"log _Return({func_id})" if mutability == "@payable" else ""

        return f"""
@external
{mutability}
def foo{func_id}({args}) -> uint256:
    {_log_return}
    return {func_id}
    """

    @given(_input=generate_methods(max_calldata_bytes))
    @settings(max_examples=125)
    def _test(_input):
        max_default_args, default_fn_mutability, methods = _input

        func_defs = "\n".join(
            generate_func_def(func_id, mutability, calldata_words, n_default_args)
            for (func_id, mutability, calldata_words, _, n_default_args) in (methods)
        )

        if default_fn_mutability == "":
            default_fn_code = ""
        elif default_fn_mutability in ("@nonpayable", "@payable"):
            default_fn_code = f"""
@external
{default_fn_mutability}
def __default__():
    log CalledDefault()
            """
        else:
            # can't log from pure/view functions, just test that it returns
            default_fn_code = """
@external
def __default__():
    pass
            """

        code = f"""
event CalledDefault:
    pass

event _Return:
    val: uint256

{func_defs}

{default_fn_code}
        """

        c = get_contract(code, override_opt_level=opt_level)

        for func_id, mutability, n_calldata_words, n_strip_bytes, n_default_args in methods:
            funcname = f"foo{func_id}"
            func = getattr(c, funcname)

            for j in range(n_default_args + 1):
                args = [[1] * n_calldata_words] if n_calldata_words else []
                args.extend([1] * j)

                # check the function returns as expected
                assert func(*args) == func_id

                method_id = utils.method_id(abi_sig(func_id, n_calldata_words, j))

                argsdata = b"\x00" * (n_calldata_words * 32 + j * 32)

                # do payable check
                if mutability == "@payable":
                    tx = func(*args, transact={"value": 1})
                    (event,) = get_logs(tx, c, "_Return")
                    assert event.args.val == func_id
                else:
                    hexstr = (method_id + argsdata).hex()
                    txdata = {"to": c.address, "data": hexstr, "value": 1}
                    with tx_failed():
                        w3.eth.send_transaction(txdata)

                # now do calldatasize check
                # strip some bytes
                calldata = (method_id + argsdata)[:-n_strip_bytes]
                hexstr = calldata.hex()
                tx_params = {"to": c.address, "data": hexstr}
                if n_calldata_words == 0 and j == 0:
                    # no args, hit default function
                    if default_fn_mutability == "":
                        with tx_failed():
                            w3.eth.send_transaction(tx_params)
                    elif default_fn_mutability == "@payable":
                        # we should be able to send eth to it
                        tx_params["value"] = 1
                        tx = w3.eth.send_transaction(tx_params)
                        logs = get_logs(tx, c, "CalledDefault")
                        assert len(logs) == 1
                    else:
                        tx = w3.eth.send_transaction(tx_params)

                        # note: can't emit logs from view/pure functions,
                        # so the logging is not tested.
                        if default_fn_mutability == "@nonpayable":
                            logs = get_logs(tx, c, "CalledDefault")
                            assert len(logs) == 1

                        # check default function reverts
                        tx_params["value"] = 1
                        with tx_failed():
                            w3.eth.send_transaction(tx_params)
                else:
                    with tx_failed():
                        w3.eth.send_transaction(tx_params)

    _test()
