import concurrent.futures
import threading

import vyper.codegen.context as codegen_context
from vyper.codegen import core
from vyper.compiler.settings import Settings, anchor_settings, get_global_settings
from vyper.semantics.namespace import Namespace, get_namespace, override_global_namespace


def _run_in_parallel(fn, args):
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(args)) as executor:
        return list(executor.map(fn, args))


def test_settings_are_isolated_between_threads():
    barrier = threading.Barrier(2)
    settings = (Settings(evm_version="london"), Settings(evm_version="cancun"))

    def worker(thread_settings):
        with anchor_settings(thread_settings):
            barrier.wait()
            current = get_global_settings()
            barrier.wait()

        return current, get_global_settings()

    results = _run_in_parallel(worker, settings)

    assert [current for current, _ in results] == list(settings)
    assert all(restored is None for _, restored in results)


def test_namespaces_are_isolated_between_threads():
    barrier = threading.Barrier(2)
    namespaces = (Namespace(), Namespace())

    def worker(namespace):
        with override_global_namespace(namespace):
            barrier.wait()
            current = get_namespace()
            barrier.wait()

        return current

    assert _run_in_parallel(worker, namespaces) == list(namespaces)


def test_codegen_counters_are_isolated_between_threads():
    barrier = threading.Barrier(2)

    def worker(_):
        core.reset_names()
        barrier.wait()
        result = core._freshname("label"), codegen_context._generate_alloca_id()
        barrier.wait()
        return result

    assert _run_in_parallel(worker, (None, None)) == [("label1", 1), ("label1", 1)]
