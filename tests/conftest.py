from contextlib import contextmanager

import hypothesis
import pytest
from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.exceptions import TransactionFailed
from hexbytes import HexBytes

import vyper.evm.opcodes as evm_opcodes
from tests.evm_backends.abi_contract import ABIContract
from tests.evm_backends.pyevm_env import PyEvmEnv
from tests.evm_backends.revm_env import RevmEnv
from tests.utils import working_directory
from vyper import compiler
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FilesystemInputBundle, InputBundle
from vyper.compiler.settings import OptimizationLevel, Settings, _set_debug_mode
from vyper.exceptions import EvmVersionException
from vyper.ir import compile_ir, optimizer
from vyper.utils import keccak256

# Import the base fixtures
pytest_plugins = ["tests.fixtures.memorymock"]

############
# PATCHING #
############


# disable hypothesis deadline globally
hypothesis.settings.register_profile("ci", deadline=None)
hypothesis.settings.load_profile("ci")


def pytest_addoption(parser):
    parser.addoption(
        "--optimize",
        choices=["codesize", "gas", "none"],
        default="gas",
        help="change optimization mode",
    )
    parser.addoption("--enable-compiler-debug-mode", action="store_true")
    parser.addoption("--experimental-codegen", action="store_true")
    parser.addoption("--tracing", action="store_true")

    parser.addoption(
        "--evm-version",
        choices=list(evm_opcodes.EVM_VERSIONS.keys()),
        default="shanghai",
        help="set evm version",
    )

    parser.addoption(
        "--evm-backend", choices=["py-evm", "revm"], default="revm", help="set evm backend"
    )


@pytest.fixture(scope="module")
def output_formats():
    output_formats = compiler.OUTPUT_FORMATS.copy()
    del output_formats["bb"]
    del output_formats["bb_runtime"]
    del output_formats["cfg"]
    del output_formats["cfg_runtime"]
    return output_formats


@pytest.fixture(scope="module")
def optimize(pytestconfig):
    flag = pytestconfig.getoption("optimize")
    return OptimizationLevel.from_string(flag)


@pytest.fixture(scope="session", autouse=True)
def debug(pytestconfig):
    debug = pytestconfig.getoption("enable_compiler_debug_mode")
    assert isinstance(debug, bool)
    _set_debug_mode(debug)


@pytest.fixture(scope="session")
def experimental_codegen(pytestconfig):
    ret = pytestconfig.getoption("experimental_codegen")
    assert isinstance(ret, bool)
    return ret


@pytest.fixture(autouse=True)
def check_venom_xfail(request, experimental_codegen):
    if not experimental_codegen:
        return

    marker = request.node.get_closest_marker("venom_xfail")
    if marker is None:
        return

    # https://github.com/okken/pytest-runtime-xfail?tab=readme-ov-file#alternatives
    request.node.add_marker(pytest.mark.xfail(strict=True, **marker.kwargs))


@pytest.fixture
def venom_xfail(request, experimental_codegen):
    def _xfail(*args, **kwargs):
        if not experimental_codegen:
            return
        request.node.add_marker(pytest.mark.xfail(*args, strict=True, **kwargs))

    return _xfail


@pytest.fixture(scope="session", autouse=True)
def evm_version(pytestconfig):
    version = pytestconfig.getoption("evm_version")
    # note: configure the evm version that we emit code for.
    # The env will read this fixture and apply the evm version there.
    evm_opcodes.DEFAULT_EVM_VERSION = version
    # This should get overridden by anchor_evm_version, but set it anyway
    evm_opcodes.active_evm_version = evm_opcodes.EVM_VERSIONS[version]
    return version


@pytest.fixture(scope="session", autouse=True)
def evm_backend(pytestconfig):
    backend_str = pytestconfig.getoption("evm_backend")
    return {"py-evm": PyEvmEnv, "revm": RevmEnv}[backend_str]


@pytest.fixture(scope="session", autouse=True)
def tracing(pytestconfig):
    return pytestconfig.getoption("tracing")


@pytest.fixture
def chdir_tmp_path(tmp_path):
    # this is useful for when you want imports to have relpaths
    with working_directory(tmp_path):
        yield


# CMC 2024-03-01 this doesn't need to be a fixture
@pytest.fixture
def keccak():
    return keccak256


@pytest.fixture
def make_file(tmp_path):
    # writes file_contents to file_name, creating it in the
    # tmp_path directory. returns final path.
    def fn(file_name, file_contents):
        path = tmp_path / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            f.write(file_contents)

        return path

    return fn


# this can either be used for its side effects (to prepare a call
# to get_contract), or the result can be provided directly to
# compile_code / CompilerData.
@pytest.fixture
def make_input_bundle(tmp_path, make_file):
    def fn(sources_dict):
        for file_name, file_contents in sources_dict.items():
            make_file(file_name, file_contents)
        return FilesystemInputBundle([tmp_path])

    return fn


# for tests which just need an input bundle, doesn't matter what it is
@pytest.fixture
def dummy_input_bundle():
    return InputBundle([])


@pytest.fixture(scope="module")
def gas_limit():
    # set absurdly high gas limit so that london basefee never adjusts
    # (note: 2**63 - 1 is max that py-evm allows)
    return 10**10


@pytest.fixture(scope="module")
def env(gas_limit, evm_version, evm_backend, tracing) -> PyEvmEnv | RevmEnv:
    return evm_backend(
        gas_limit=gas_limit,
        tracing=tracing,
        block_number=1,
        evm_version=evm_version,
        account_keys=get_default_account_keys(),
    )


@pytest.fixture
def get_contract_from_ir(env, optimize):
    def ir_compiler(ir, *args, **kwargs):
        ir = IRnode.from_list(ir)
        if kwargs.pop("optimize", optimize) != OptimizationLevel.NONE:
            ir = optimizer.optimize(ir)

        assembly = compile_ir.compile_to_assembly(ir, optimize=optimize)
        bytecode, _ = compile_ir.assembly_to_evm(assembly)

        abi = kwargs.pop("abi", [])
        return env.deploy(abi, bytecode, *args, **kwargs)

    return ir_compiler


@pytest.fixture(scope="module")
def compiler_settings(optimize, experimental_codegen, evm_version):
    return Settings(
        optimize=optimize, evm_version=evm_version, experimental_codegen=experimental_codegen
    )


@pytest.fixture(scope="module")
def get_contract(env, optimize, output_formats, compiler_settings):
    def fn(source_code, *args, **kwargs):
        settings = kwargs.pop("compiler_settings", compiler_settings)
        if "override_opt_level" in kwargs:
            settings = Settings(
                **dict(settings.__dict__, optimize=kwargs.pop("override_opt_level"))
            )
        return env.deploy_source(source_code, output_formats, settings, *args, **kwargs)

    return fn


@pytest.fixture(scope="module")
def deploy_blueprint_for(env, compiler_settings, output_formats):
    def fn(source_code, *args, **kwargs):
        settings = kwargs.pop("compiler_settings", compiler_settings)
        if "override_opt_level" in kwargs:
            settings = Settings(
                **dict(settings.__dict__, optimize=kwargs.pop("override_opt_level"))
            )
        return env.deploy_blueprint(source_code, output_formats, settings, *args, **kwargs)

    return fn


@pytest.fixture(scope="module")
def get_logs(env):
    def fn(c: ABIContract, event_name: str = None, raw=False):
        logs = [log for log in env.last_result["logs"] if c.address == log.address]
        if raw:
            return [log.data for log in logs]

        parsed_logs = [c.parse_log(log) for log in logs]
        if event_name:
            return [log for log in parsed_logs if log.event == event_name]

        return parsed_logs

    return fn


# TODO: this should not be a fixture.
# remove me and replace all uses with `with pytest.raises`.
@pytest.fixture
def assert_compile_failed():
    def assert_compile_failed(function_to_test, exception=Exception):
        with pytest.raises(exception):
            function_to_test()

    return assert_compile_failed


@pytest.fixture
def create2_address_of(keccak):
    def _f(_addr, _salt, _initcode):
        prefix = HexBytes("0xff")
        addr = HexBytes(_addr)
        salt = HexBytes(_salt)
        initcode = HexBytes(_initcode)
        return keccak(prefix + addr + salt + keccak(initcode))[12:]

    return _f


@pytest.fixture
def side_effects_contract(get_contract):
    def generate(ret_type):
        """
        Generates a Vyper contract with an external `foo()` function, which
        returns the specified return value of the specified return type, for
        testing side effects using the `assert_side_effects_invoked` fixture.
        """
        code = f"""
counter: public(uint256)

@external
def foo(s: {ret_type}) -> {ret_type}:
    self.counter += 1
    return s
    """
        return get_contract(code)

    return generate


@pytest.fixture
def assert_side_effects_invoked():
    def assert_side_effects_invoked(side_effects_contract, side_effects_trigger, n=1):
        start_value = side_effects_contract.counter()

        side_effects_trigger()

        end_value = side_effects_contract.counter()
        assert end_value == start_value + n

    return assert_side_effects_invoked


@pytest.fixture(scope="module")
def tx_failed(env):
    # todo: use custom exception, we don't use eth_tester anymore
    @contextmanager
    def fn(exception=TransactionFailed, exc_text=None):
        with env.anchor(), pytest.raises(exception) as excinfo:
            yield excinfo

        if exc_text:
            # TODO test equality
            assert exc_text in str(excinfo.value), (exc_text, excinfo.value)

    return fn


def pytest_runtest_call(item):
    marker = item.get_closest_marker("requires_evm_version")
    if marker:
        assert len(marker.args) == 1
        version = marker.args[0]
        if not evm_opcodes.version_check(begin=version):
            item.add_marker(
                pytest.mark.xfail(reason="Wrong EVM version", raises=EvmVersionException)
            )
