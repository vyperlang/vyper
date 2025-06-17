def test_import_flag_types(make_input_bundle, get_contract):
    lib1 = """
import lib2

flag Roles:
    ADMIN
    USER

enum Roles2:
    ADMIN
    USER

role: Roles
role2: Roles2
role3: lib2.Roles3
    """
    lib2 = """
flag Roles3:
    ADMIN
    USER
    NOBODY
    """
    contract = """
import lib1

initializes: lib1

@external
def bar(r: lib1.Roles, r2: lib1.Roles2, r3: lib1.lib2.Roles3) -> bool:
    lib1.role = r
    lib1.role2 = r2
    lib1.role3 = r3
    assert lib1.role == lib1.Roles.ADMIN
    assert lib1.role2 == lib1.Roles2.USER
    assert lib1.role3 == lib1.lib2.Roles3.NOBODY
    return True
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    c = get_contract(contract, input_bundle=input_bundle)
    assert c.bar(1, 2, 4) is True
