from typing import Iterable, Sequence

from vyper.exceptions import CompilerPanic
from vyper.venom.passes.base_pass import IRPass, PassRef


def validate_pass_order(pass_classes: Sequence[type[IRPass]], pipeline_name: str) -> None:
    """
    Validate ordering constraints declared on each pass class.
    """
    pass_names = [pass_cls.__name__ for pass_cls in pass_classes]

    for idx, pass_cls in enumerate(pass_classes):
        _validate_non_immediate(
            pass_names,
            idx,
            pass_cls,
            pass_cls.required_predecessors,
            pipeline_name,
            direction="before",
        )
        _validate_non_immediate(
            pass_names,
            idx,
            pass_cls,
            pass_cls.required_successors,
            pipeline_name,
            direction="after",
        )
        _validate_immediate(
            pass_names,
            idx,
            pass_cls,
            pass_cls.required_immediate_predecessors,
            pipeline_name,
            direction="before",
        )
        _validate_immediate(
            pass_names,
            idx,
            pass_cls,
            pass_cls.required_immediate_successors,
            pipeline_name,
            direction="after",
        )


def _validate_non_immediate(
    pass_names: list[str],
    idx: int,
    pass_cls: type[IRPass],
    refs: tuple[PassRef, ...],
    pipeline_name: str,
    direction: str,
) -> None:
    candidates = _normalize_refs(refs)
    if not candidates:
        return

    if direction == "before":
        search_space = pass_names[:idx]
        relation = "must run after"
    else:
        search_space = pass_names[idx + 1 :]
        relation = "must run before"

    if not any(candidate in search_space for candidate in candidates):
        _raise_pass_order_error(
            idx=idx,
            pass_cls=pass_cls,
            expected=candidates,
            relation=relation,
            pipeline_name=pipeline_name,
        )


def _validate_immediate(
    pass_names: list[str],
    idx: int,
    pass_cls: type[IRPass],
    refs: tuple[PassRef, ...],
    pipeline_name: str,
    direction: str,
) -> None:
    candidates = _normalize_refs(refs)
    if not candidates:
        return

    if direction == "before":
        relation = "must run immediately after"
        actual = pass_names[idx - 1] if idx > 0 else "<start>"
    else:
        relation = "must run immediately before"
        actual = pass_names[idx + 1] if idx + 1 < len(pass_names) else "<end>"

    if actual in candidates:
        return

    _raise_pass_order_error(
        idx=idx,
        pass_cls=pass_cls,
        expected=candidates,
        relation=relation,
        pipeline_name=pipeline_name,
        actual=actual,
    )


def _normalize_refs(refs: Iterable[PassRef]) -> tuple[str, ...]:
    return tuple(_ref_name(ref) for ref in refs)


def _ref_name(ref: PassRef) -> str:
    if isinstance(ref, str):
        return ref
    return ref.__name__


def _raise_pass_order_error(
    *,
    idx: int,
    pass_cls: type[IRPass],
    expected: tuple[str, ...],
    relation: str,
    pipeline_name: str,
    actual: str | None = None,
) -> None:
    expected_display = ", ".join(expected)
    message = (
        f"Invalid Venom pass ordering in '{pipeline_name}': {pass_cls.__name__} "
        f"(index {idx}) {relation} one of [{expected_display}]."
    )
    if actual is not None:
        message += f" Got {actual} instead."
    raise CompilerPanic(message)
