import vyper


# test that each compilation run gets a fresh analysis and storage allocator
def test_shared_modules_allocation(make_input_bundle):
    lib1 = """
x: uint256
    """
    main1 = """
import lib1
initializes: lib1
    """
    main2 = """
import lib1
initializes: lib1
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    vyper.compile_code(main1, input_bundle=input_bundle)
    vyper.compile_code(main2, input_bundle=input_bundle)
