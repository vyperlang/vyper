from tests.venom_utils import parse_venom
from vyper.venom.analysis import IRAnalysesCache, IRGlobalAnalysesCache
from vyper.venom.analysis.readonly_memory_args import ReadonlyMemoryArgsGlobalAnalysis
from vyper.venom.basicblock import IRLabel


def _analyze_readonly_args(src: str):
    ctx = parse_venom(src)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    ctx.global_analyses_cache = IRGlobalAnalysesCache(ctx, analyses)
    readonly_analysis = ctx.global_analyses_cache.request_analysis(ReadonlyMemoryArgsGlobalAnalysis)
    return ctx, readonly_analysis


def test_analysis_returns_indices_without_mutating_functions():
    src = """
    function entry {
    entry:
        %arg = param
        mload %arg
        stop
    }
    """

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("entry"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == (0,)
    assert not hasattr(fn, "_readonly_memory_invoke_arg_idxs")


def test_add_write_marks_param_mutable():
    src = """
    function f {
    f:
        %arg = param
        %retpc = param
        %ptr = add 32, %arg
        mstore %ptr, 1
        ret %retpc
    }
    """

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("f"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == ()


def test_add_read_keeps_param_readonly():
    src = """
    function f {
    f:
        %arg = param
        %retpc = param
        %ptr = add 32, %arg
        %val = mload %ptr
        ret %retpc
    }
    """

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("f"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == (0,)


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

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("f"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == ()


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

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("f"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == ()


def test_function_without_retpc_keeps_all_params():
    src = """
    function entry {
    entry:
        %arg = param
        mload %arg
        stop
    }
    """

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("entry"))
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == (0,)


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

    ctx, readonly_analysis = _analyze_readonly_args(src)
    fn = ctx.get_function(IRLabel("f"))
    # `%arg` is conservatively mutable due unknown invoke target.
    # `%target` stays readonly because it is only used as call target.
    assert readonly_analysis.get_readonly_invoke_arg_idxs(fn) == (0,)
