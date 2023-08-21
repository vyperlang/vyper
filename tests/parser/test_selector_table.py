import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

import vyper.utils as utils
from vyper.codegen.jumptable_utils import (
    generate_dense_jumptable_info,
    generate_sparse_jumptable_buckets,
)
from vyper.compiler.settings import OptimizationLevel


@given(
    n_methods=st.integers(min_value=1, max_value=100),
    seed=st.integers(min_value=0, max_value=2**64 - 1),
)
@pytest.mark.fuzzing
@settings(max_examples=10, deadline=None)
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
@settings(max_examples=10, deadline=None)
def test_dense_jumptable_bucket_size(n_methods, seed):
    sigs = [f"foo{i + seed}()" for i in range(n_methods)]
    n = len(sigs)
    buckets = generate_dense_jumptable_info(sigs)
    n_buckets = len(buckets)

    # generally should be around 14 buckets per 100 methods, here
    # we test they don't get really out of hand
    assert n_buckets / n < 0.4 or n < 10


@pytest.mark.parametrize("opt_level", list(OptimizationLevel))
# dense selector table packing boundaries at 256 and 65336
@pytest.mark.parametrize("max_calldata_bytes", [255, 256, 65336])
@settings(max_examples=5, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=2**64 - 1),
    max_default_args=st.integers(min_value=0, max_value=4),
    default_fn_mutability=st.sampled_from(["", "@pure", "@view", "@nonpayable", "@payable"]),
)
@pytest.mark.fuzzing
def test_selector_table_fuzz(
    max_calldata_bytes,
    seed,
    max_default_args,
    opt_level,
    default_fn_mutability,
    w3,
    get_contract,
    assert_tx_failed,
    get_logs,
):
    def abi_sig(calldata_words, i, n_default_args):
        args = [] if not calldata_words else [f"uint256[{calldata_words}]"]
        args.extend(["uint256"] * n_default_args)
        argstr = ",".join(args)
        return f"foo{seed + i}({argstr})"

    def generate_func_def(mutability, calldata_words, i, n_default_args):
        arglist = [] if not calldata_words else [f"x: uint256[{calldata_words}]"]
        for j in range(n_default_args):
            arglist.append(f"x{j}: uint256 = 0")
        args = ", ".join(arglist)
        _log_return = f"log _Return({i})" if mutability == "@payable" else ""

        return f"""
@external
{mutability}
def foo{seed + i}({args}) -> uint256:
    {_log_return}
    return {i}
    """

    @given(
        methods=st.lists(
            st.tuples(
                st.sampled_from(["@pure", "@view", "@nonpayable", "@payable"]),
                st.integers(min_value=0, max_value=max_calldata_bytes // 32),
                # n bytes to strip from calldata
                st.integers(min_value=1, max_value=4),
                # n default args
                st.integers(min_value=0, max_value=max_default_args),
            ),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=25)
    def _test(methods):
        func_defs = "\n".join(
            generate_func_def(m, s, i, d) for i, (m, s, _, d) in enumerate(methods)
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

        for i, (mutability, n_calldata_words, n_strip_bytes, n_default_args) in enumerate(methods):
            funcname = f"foo{seed + i}"
            func = getattr(c, funcname)

            for j in range(n_default_args + 1):
                args = [[1] * n_calldata_words] if n_calldata_words else []
                args.extend([1] * j)

                # check the function returns as expected
                assert func(*args) == i

                method_id = utils.method_id(abi_sig(n_calldata_words, i, j))

                argsdata = b"\x00" * (n_calldata_words * 32 + j * 32)

                # do payable check
                if mutability == "@payable":
                    tx = func(*args, transact={"value": 1})
                    (event,) = get_logs(tx, c, "_Return")
                    assert event.args.val == i
                else:
                    hexstr = (method_id + argsdata).hex()
                    txdata = {"to": c.address, "data": hexstr, "value": 1}
                    assert_tx_failed(lambda: w3.eth.send_transaction(txdata))

                # now do calldatasize check
                # strip some bytes
                calldata = (method_id + argsdata)[:-n_strip_bytes]
                hexstr = calldata.hex()
                tx_params = {"to": c.address, "data": hexstr}
                if n_calldata_words == 0 and j == 0:
                    # no args, hit default function
                    if default_fn_mutability == "":
                        assert_tx_failed(lambda: w3.eth.send_transaction(tx_params))
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
                        assert_tx_failed(lambda: w3.eth.send_transaction(tx_params))
                else:
                    assert_tx_failed(lambda: w3.eth.send_transaction(tx_params))

    _test()
