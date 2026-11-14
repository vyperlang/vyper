import asyncio
import concurrent.futures
import contextvars
import threading

import pytest

import vyper.codegen.context as codegen_context
from vyper.codegen import core
from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings, anchor_settings, get_global_settings
from vyper.exceptions import UndeclaredDefinition
from vyper.semantics.analysis.module import ModuleAnalyzer
from vyper.semantics.namespace import Namespace, get_namespace, override_global_namespace


def _run_in_parallel(fn, args, copy_contexts=False):
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args)) as executor:
        if copy_contexts:
            futures = [executor.submit(contextvars.copy_context().run, fn, arg) for arg in args]
            return [future.result() for future in futures]
        return list(executor.map(fn, args))


@pytest.mark.parametrize("copy_contexts", [False, True])
def test_settings_are_isolated_between_threads(copy_contexts):
    barrier = threading.Barrier(2, timeout=10)
    settings = (Settings(evm_version="london"), Settings(evm_version="cancun"))
    parent_settings = get_global_settings()

    def worker(thread_settings):
        with anchor_settings(thread_settings):
            barrier.wait()
            current = get_global_settings()
            barrier.wait()

        return current, get_global_settings()

    results = _run_in_parallel(worker, settings, copy_contexts)

    assert [current for current, _ in results] == list(settings)
    expected = parent_settings if copy_contexts else None
    assert all(restored is expected for _, restored in results)
    assert get_global_settings() is parent_settings


def test_namespaces_are_isolated_between_threads():
    barrier = threading.Barrier(2, timeout=10)
    namespaces = (Namespace(), Namespace())

    def worker(namespace):
        with override_global_namespace(namespace), get_namespace().enter_scope():
            get_namespace()["thread_marker"] = namespace
            barrier.wait()
            current = get_namespace()
            assert current["thread_marker"] is namespace
            barrier.wait()

        return current

    assert _run_in_parallel(worker, namespaces) == list(namespaces)
    assert all("thread_marker" not in namespace for namespace in namespaces)
    assert all(not namespace._scopes for namespace in namespaces)


@pytest.mark.parametrize("copy_contexts", [False, True])
def test_codegen_counters_are_isolated_between_threads(copy_contexts):
    barrier = threading.Barrier(2, timeout=10)
    core.reset_names()
    assert (core._freshname("parent"), codegen_context._generate_alloca_id()) == ("parent1", 1)

    def worker(_):
        core.reset_names()
        barrier.wait()
        result = core._freshname("label"), codegen_context._generate_alloca_id()
        barrier.wait()
        return result

    assert _run_in_parallel(worker, (None, None), copy_contexts) == [("label1", 1), ("label1", 1)]
    assert (core._freshname("parent"), codegen_context._generate_alloca_id()) == ("parent2", 2)


@pytest.mark.parametrize("context_mode", ["threads", "copy_context", "asyncio"])
@pytest.mark.parametrize("lazy", [False, True], ids=["compile_code", "compiler_data"])
def test_compilation_namespaces_are_isolated(monkeypatch, compiler_settings, context_mode, lazy):
    sources = [f"""
VALUE: constant(uint256) = {value}

@external
@pure
def foo() -> uint256:
    return VALUE
""" for value in (1, 2)]

    def compile_source(source):
        if lazy:
            data = CompilerData(source, settings=compiler_settings)
            with anchor_settings(data.settings):
                return data.bytecode.hex()
        return compile_code(source, settings=compiler_settings)["bytecode"][2:]

    expected = [compile_source(source) for source in sources]
    parent_namespace = get_namespace()
    barrier = threading.Barrier(2, timeout=10)
    analyze_module_body = ModuleAnalyzer.analyze_module_body

    def analyze_with_barrier(analyzer):
        namespace = get_namespace()
        assert get_global_settings() is not compiler_settings
        assert namespace is not parent_namespace
        assert "parent_marker" not in namespace
        assert len(namespace._scopes) == 1
        marker = object()
        namespace["compilation_marker"] = marker
        barrier.wait()
        analyze_module_body(analyzer)
        barrier.wait()
        assert namespace["compilation_marker"] is marker

    async def run_async():
        return await asyncio.gather(
            *(asyncio.to_thread(compile_source, source) for source in sources)
        )

    with parent_namespace.enter_scope():
        marker = object()
        parent_namespace["parent_marker"] = marker
        monkeypatch.setattr(ModuleAnalyzer, "analyze_module_body", analyze_with_barrier)

        if context_mode == "asyncio":
            results = asyncio.run(run_async())
        else:
            results = _run_in_parallel(
                compile_source, sources, copy_contexts=context_mode == "copy_context"
            )

        assert results == expected
        assert get_namespace() is parent_namespace
        assert parent_namespace["parent_marker"] is marker
        assert "compilation_marker" not in parent_namespace
        assert len(parent_namespace._scopes) == 1


def test_compilation_restores_namespace_after_error():
    namespace = get_namespace()
    with namespace.enter_scope():
        marker = object()
        namespace["parent_marker"] = marker
        with pytest.raises(UndeclaredDefinition):
            compile_code("@external\ndef foo():\n    missing_name()")
        assert get_namespace() is namespace
        assert namespace["parent_marker"] is marker
        assert len(namespace._scopes) == 1
