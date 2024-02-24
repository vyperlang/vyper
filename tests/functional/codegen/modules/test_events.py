
def test_module_event(get_contract, make_input_bundle, get_logs):
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    main = """
import lib1

@external
def bar():
    lib1.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    logs = get_logs(c.bar(transact={}), c, "MyEvent")
    assert len(logs) == 1

def test_module_event2(get_contract, make_input_bundle, get_logs):
    lib1 = """
event MyEvent:
    pass
    """
    main = """
import lib1

@external
def bar():
    log lib1.MyEvent()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    logs = get_logs(c.bar(transact={}), c, "MyEvent")
    assert len(logs) == 1
