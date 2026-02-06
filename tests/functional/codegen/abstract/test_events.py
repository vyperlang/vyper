def test_event_from_override_appears_in_abi(get_contract, make_input_bundle, get_logs):
    abstract_module = """
event MyEvent:
    value: uint256

@external
def call_abstract() -> uint256:
    return self.process()

@abstract
def process() -> uint256: ...
    """

    contract = """
import abstract_module

initializes: abstract_module

exports: abstract_module.call_abstract

@override(abstract_module)
def process() -> uint256:
    log abstract_module.MyEvent(value=42)
    return 42
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})
    c = get_contract(contract, input_bundle=input_bundle)

    result = c.call_abstract()
    assert result == 42

    logs = get_logs(c, "MyEvent")
    assert len(logs) == 1
    assert logs[0].args.value == 42


def test_event_from_function_called_by_override(get_contract, make_input_bundle, get_logs):
    abstract_module = """
event MyEvent:
    value: uint256

@external
def call_abstract() -> uint256:
    return self.process()

def log_event(x: uint256):
    log MyEvent(value=x)

@abstract
def process() -> uint256: ...
    """

    contract = """
import abstract_module

initializes: abstract_module

exports: abstract_module.call_abstract

@override(abstract_module)
def process() -> uint256:
    abstract_module.log_event(123)
    return 123
    """

    input_bundle = make_input_bundle({"abstract_module.vy": abstract_module})
    c = get_contract(contract, input_bundle=input_bundle)

    result = c.call_abstract()
    assert result == 123

    logs = get_logs(c, "MyEvent")
    assert len(logs) == 1
    assert logs[0].args.value == 123


def test_event_from_nested_override_calls(get_contract, make_input_bundle, get_logs):
    helper_module = """
event HelperEvent:
    data: uint256

def helper(x: uint256) -> uint256:
    log HelperEvent(data=x)
    return x * 2
    """

    abstract_module = """
@external
def exposed() -> uint256:
    return self.process()

@abstract
def process() -> uint256: ...
    """

    contract = """
import abstract_module
import helper_module

initializes: abstract_module
initializes: helper_module

exports: abstract_module.exposed

@override(abstract_module)
def process() -> uint256:
    return helper_module.helper(50)
    """

    input_bundle = make_input_bundle(
        {"helper_module.vy": helper_module, "abstract_module.vy": abstract_module}
    )
    c = get_contract(contract, input_bundle=input_bundle)

    result = c.exposed()
    assert result == 100  # 50 * 2

    logs = get_logs(c, "HelperEvent")
    assert len(logs) == 1
    assert logs[0].args.data == 50
