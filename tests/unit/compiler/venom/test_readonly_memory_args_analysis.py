from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.passes import ReadonlyMemoryArgsAnalysisPass


def _run_readonly_analysis(src: str):
    ctx = parse_venom(src)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    ReadonlyMemoryArgsAnalysisPass(analyses, ctx).run_pass()
    return ctx


def test_gep_write_marks_param_mutable():
    src = """
    function f {
    f:
        %arg = param
        %retpc = param
        %ptr = gep 32, %arg
        mstore %ptr, 1
        ret %retpc
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("f"))
    assert fn._readonly_memory_invoke_arg_idxs == ()


def test_gep_read_keeps_param_readonly():
    src = """
    function f {
    f:
        %arg = param
        %retpc = param
        %ptr = gep 32, %arg
        %val = mload %ptr
        ret %retpc
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("f"))
    assert fn._readonly_memory_invoke_arg_idxs == (0,)


def test_add_of_two_params_marks_both_mutable():
    src = """
    function f {
    f:
        %a = param
        %b = param
        %retpc = param
        %ptr = add %a, %b
        mstore %ptr, 1
        ret %retpc
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("f"))
    assert fn._readonly_memory_invoke_arg_idxs == ()


def test_phi_of_two_params_marks_both_mutable():
    src = """
    function f {
    f:
        %a = param
        %b = param
        %retpc = param
        jnz %a, @left, @right

    left:
        jmp @merge

    right:
        jmp @merge

    merge:
        %ptr = phi @left, %a, @right, %b
        mstore %ptr, 1
        ret %retpc
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("f"))
    assert fn._readonly_memory_invoke_arg_idxs == ()


def test_function_without_retpc_keeps_all_params():
    src = """
    function entry {
    entry:
        %arg = param
        mload %arg
        stop
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("entry"))
    assert fn._readonly_memory_invoke_arg_idxs == (0,)


def test_non_label_invoke_target_marks_args_mutable():
    src = """
    function f {
    f:
        %target = param
        %arg = param
        %retpc = param
        invoke %target, %arg
        ret %retpc
    }
    """

    ctx = _run_readonly_analysis(src)
    fn = ctx.get_function(IRLabel("f"))
    # `%arg` is conservatively mutable due unknown invoke target.
    # `%target` stays readonly because it is only used as call target.
    assert fn._readonly_memory_invoke_arg_idxs == (0,)
