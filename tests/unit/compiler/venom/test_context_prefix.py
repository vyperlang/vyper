import pytest

from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext


def _fn_labels(ctx: IRContext) -> list[str]:
    return sorted(label.value for label in ctx.functions)


def _section_labels(ctx: IRContext) -> list[str]:
    return [section.label.value for section in ctx.data_segment]


@pytest.mark.parametrize(
    "prefix, expected_fn, expected_section, expected_label",
    [("", "foo", "tbl", "1"), ("m1", "m1_foo", "m1_tbl", "m1_1")],
)
def test_prefix_applies_to_generated_names(prefix, expected_fn, expected_section, expected_label):
    ctx = IRContext(prefix=prefix)
    fn = ctx.create_function("foo")
    ctx.append_data_section("tbl")
    label = ctx.get_next_label()

    assert fn.name.value == expected_fn
    assert _section_labels(ctx) == [expected_section]
    assert label.value == expected_label


def test_prefix_applies_to_labeled_helpers():
    assert IRContext(prefix="m1").prefixed_label("foo").value == "m1_foo"
    assert IRContext().prefixed_label("foo").value == "foo"


def test_explicit_irlabel_passes_through():
    # IRLabel arg is used as-is; only str input to append_data_section is auto-prefixed.
    ctx = IRContext(prefix="m1")
    ctx.append_data_section(IRLabel("user_built", is_symbol=True))
    assert _section_labels(ctx) == ["user_built"]


def test_prefix_applies_to_suffixed_labels():
    ctx = IRContext(prefix="m1")
    assert ctx.get_next_label("loop").value == "m1_1_loop"


def test_merge_moves_state_and_clears_sources():
    a = IRContext(prefix="a")
    a.entry_function = a.create_function("foo")
    a.append_data_section("v")

    b = IRContext(prefix="b")
    b.create_function("bar")
    b.append_data_section("w")

    target = IRContext()
    assert target.merge(a, b) is target

    assert _fn_labels(target) == ["a_foo", "b_bar"]
    assert _section_labels(target) == ["a_v", "b_w"]

    assert a.functions == {}
    assert a.data_segment == []
    assert a.entry_function is None
    assert b.functions == {}
    assert b.data_segment == []


@pytest.mark.parametrize(
    "target_prefix, src1_prefix, src2_prefix, expected_message",
    [("", "dup", "dup", "duplicate function"), ("t", "t", None, "duplicate function")],
)
def test_merge_raises_on_duplicate_function_labels(
    target_prefix, src1_prefix, src2_prefix, expected_message
):
    target = IRContext(prefix=target_prefix)
    if target_prefix:
        target.create_function("foo")

    src1 = IRContext(prefix=src1_prefix)
    src1.create_function("foo")

    with pytest.raises(ValueError, match=expected_message):
        if src2_prefix is None:
            target.merge(src1)
        else:
            src2 = IRContext(prefix=src2_prefix)
            src2.create_function("foo")
            target.merge(src1, src2)


def test_merge_raises_on_duplicate_basic_block_labels():
    # Distinct function names but a shared prefix → bb labels from get_next_label collide.
    a = IRContext(prefix="m")
    fn_a = a.create_function("foo")
    fn_a.append_basic_block(IRBasicBlock(a.get_next_label(), fn_a))

    b = IRContext(prefix="m")
    fn_b = b.create_function("bar")
    fn_b.append_basic_block(IRBasicBlock(b.get_next_label(), fn_b))

    with pytest.raises(ValueError, match="duplicate basic block label"):
        IRContext().merge(a, b)


def test_merge_raises_on_duplicate_data_section_label():
    a = IRContext(prefix="dup")
    b = IRContext(prefix="dup")
    a.append_data_section("tbl")
    b.append_data_section("tbl")

    with pytest.raises(ValueError, match="duplicate data section"):
        IRContext().merge(a, b)


def test_merge_is_atomic_on_validation_failure():
    target = IRContext(prefix="t")
    target.create_function("target")
    target.append_data_section("target_tbl")

    src_ok = IRContext(prefix="good")
    src_ok.create_function("foo")
    src_ok.append_data_section("tbl")

    src_bad = IRContext(prefix="good")
    src_bad.create_function("foo")
    src_bad.append_data_section("tbl")

    with pytest.raises(ValueError, match="duplicate function"):
        target.merge(src_ok, src_bad)

    assert _fn_labels(target) == ["t_target"]
    assert _section_labels(target) == ["t_target_tbl"]
    assert _fn_labels(src_ok) == ["good_foo"]
    assert _section_labels(src_ok) == ["good_tbl"]
    assert _fn_labels(src_bad) == ["good_foo"]
    assert _section_labels(src_bad) == ["good_tbl"]


def test_prefixed_labels_roundtrip_through_parser():
    from vyper.venom.parser import parse_venom

    ctx = IRContext(prefix="m1")
    fn = ctx.create_function("foo")
    extra = IRBasicBlock(ctx.get_next_label("loop"), fn)
    fn.append_basic_block(extra)
    fn.entry.append_instruction("jmp", extra.label)
    extra.append_instruction("stop")

    parse_venom(str(ctx))


def test_merge_advances_counters_past_sources():
    src = IRContext(prefix="m")
    fn = src.create_function("foo")
    fn.append_basic_block(IRBasicBlock(src.get_next_label(), fn))  # "m_1"
    fn.append_basic_block(IRBasicBlock(src.get_next_label(), fn))  # "m_2"
    src.get_next_variable()  # "%1"
    src.get_next_variable()  # "%2"
    target = IRContext(prefix="m")
    target.merge(src)
    assert target.get_next_label().value == "m_3"
    assert target.get_next_variable().value == "%3"
