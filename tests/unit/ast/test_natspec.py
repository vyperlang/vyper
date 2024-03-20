import pytest

from vyper import ast as vy_ast
from vyper.compiler.phases import CompilerData
from vyper.exceptions import NatSpecSyntaxException

test_code = """
'''
@title A simulator for Bug Bunny, the most famous Rabbit
@license MIT
@author Warned Bros
@notice You can use this contract for only the most basic simulation
@dev
    Simply chewing a carrot does not count, carrots must pass
    the throat to be considered eaten
'''

@external
@payable
def doesEat(food: String[30], qty: uint256) -> bool:
    '''
    @notice Determine if Bugs will accept `qty` of `food` to eat
    @dev Compares the entire string and does not rely on a hash
    @param food The name of a food to evaluate (in English)
    @param qty The number of food items to evaluate
    @return True if Bugs will eat it, False otherwise
    @custom:my-custom-tag hello, world!
    '''
    return True
"""


expected_userdoc = {
    "methods": {
        "doesEat(string,uint256)": {
            "notice": "Determine if Bugs will accept `qty` of `food` to eat"
        }
    },
    "notice": "You can use this contract for only the most basic simulation",
}


expected_devdoc = {
    "author": "Warned Bros",
    "license": "MIT",
    "details": "Simply chewing a carrot does not count, carrots must pass the throat to be considered eaten",  # NOQA: E501
    "methods": {
        "doesEat(string,uint256)": {
            "details": "Compares the entire string and does not rely on a hash",
            "params": {
                "food": "The name of a food to evaluate (in English)",
                "qty": "The number of food items to evaluate",
            },
            "returns": {"_0": "True if Bugs will eat it, False otherwise"},
            "custom:my-custom-tag": "hello, world!",
        }
    },
    "title": "A simulator for Bug Bunny, the most famous Rabbit",
}


def parse_natspec(code):
    vyper_ast = CompilerData(code).annotated_vyper_module
    return vy_ast.parse_natspec(vyper_ast)


def test_documentation_example_output():
    userdoc, devdoc = parse_natspec(test_code)

    assert userdoc == expected_userdoc
    assert devdoc == expected_devdoc


def test_no_tags_implies_notice():
    code = """
'''
Because there is no tag, this docstring is handled as a notice.
'''
@external
def foo():
    '''
    This one too!
    '''
    pass
    """

    userdoc, devdoc = parse_natspec(code)

    assert userdoc == {
        "methods": {"foo()": {"notice": "This one too!"}},
        "notice": "Because there is no tag, this docstring is handled as a notice.",
    }
    assert not devdoc


def test_whitespace():
    code = """
'''
        @dev

  Whitespace    gets  cleaned
    up,
            people can use


         awful formatting.


We don't mind!

@author Mr No-linter
                '''
"""
    _, devdoc = parse_natspec(code)

    assert devdoc == {
        "author": "Mr No-linter",
        "details": "Whitespace gets cleaned up, people can use awful formatting. We don't mind!",
    }


def test_params():
    code = """
@external
def foo(bar: int128, baz: uint256, potato: bytes32):
    '''
    @param bar a number
    @param baz also a number
    @dev we didn't document potato, but that's ok
    '''
    pass
    """

    _, devdoc = parse_natspec(code)

    assert devdoc == {
        "methods": {
            "foo(int128,uint256,bytes32)": {
                "details": "we didn't document potato, but that's ok",
                "params": {"bar": "a number", "baz": "also a number"},
            }
        }
    }


def test_returns():
    code = """
@external
def foo(bar: int128, baz: uint256) -> (int128, uint256):
    '''
    @return value of bar
    @return value of baz
    '''
    return bar, baz
    """

    _, devdoc = parse_natspec(code)

    assert devdoc == {
        "methods": {
            "foo(int128,uint256)": {"returns": {"_0": "value of bar", "_1": "value of baz"}}
        }
    }


def test_ignore_private_methods():
    code = """
@external
def foo(bar: int128, baz: uint256):
    '''@dev I will be parsed.'''
    pass

@internal
def notfoo(bar: int128, baz: uint256):
    '''@dev I will not be parsed.'''
    pass
    """

    _, devdoc = parse_natspec(code)

    assert devdoc["methods"] == {"foo(int128,uint256)": {"details": "I will be parsed."}}


def test_partial_natspec():
    code = """
@external
def foo():
    '''
    Regular comments preceding natspec is not allowed
    @notice this is natspec
    '''
    pass
    """

    with pytest.raises(
        NatSpecSyntaxException, match="NatSpec docstring opens with untagged comment"
    ):
        parse_natspec(code)


empty_field_cases = [
    """
    @notice
    @dev notice shouldn't be empty
    @author nobody
    """,
    """
    @dev notice shouldn't be empty
    @notice
    @author nobody
    """,
    """
    @dev notice shouldn't be empty
    @author nobody
    @notice
    """,
]


@pytest.mark.parametrize("bad_docstring", empty_field_cases)
def test_empty_field(bad_docstring):
    code = f"""
@external
def foo():
    '''{bad_docstring}'''
    pass
    """
    with pytest.raises(NatSpecSyntaxException, match="No description given for tag '@notice'"):
        parse_natspec(code)


def test_unknown_field():
    code = """
@external
def foo():
    '''
    @notice this is ok
    @thing this is bad
    '''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match="Unknown NatSpec field '@thing'"):
        parse_natspec(code)


@pytest.mark.parametrize("field", ["title", "license"])
def test_invalid_field(field):
    code = f"""
@external
def foo():
    '''@{field} function level docstrings cannot have titles'''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match=f"'@{field}' is not a valid field"):
        parse_natspec(code)


licenses = [
    "Apache-2.0",
    "Apache-2.0 OR MIT",
    "PSF-2.0 AND MIT",
    "Apache-2.0 AND (MIT OR GPL-2.0-only)",
]


@pytest.mark.parametrize("license", licenses)
def test_license(license):
    code = f"""
'''
@license {license}
'''
@external
def foo():
    pass
    """

    _, devdoc = parse_natspec(code)

    assert devdoc == {"license": license}


fields = ["title", "author", "license", "notice", "dev"]


@pytest.mark.parametrize("field", fields)
def test_empty_fields(field):
    code = f"""
'''
@{field}
'''
@external
def foo():
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match=f"No description given for tag '@{field}'"):
        parse_natspec(code)


def test_duplicate_fields():
    code = """
@external
def foo():
    '''
    @notice It's fine to have one notice, but....
    @notice a second one, not so much
    '''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match="Duplicate NatSpec field '@notice'"):
        parse_natspec(code)


def test_duplicate_param():
    code = """
@external
def foo(bar: int128, baz: uint256):
    '''
    @param bar a number
    @param bar also a number
    '''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match="Parameter 'bar' documented more than once"):
        parse_natspec(code)


def test_unknown_param():
    code = """
@external
def foo(bar: int128, baz: uint256):
    '''@param hotdog not a number'''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match="Method has no parameter 'hotdog'"):
        parse_natspec(code)


empty_field_cases = [
    """
    @param a
    @dev param shouldn't be empty
    @author nobody
    """,
    """
    @dev param shouldn't be empty
    @param a
    @author nobody
    """,
    """
    @dev param shouldn't be empty
    @author nobody
    @param a
    """,
]


@pytest.mark.parametrize("bad_docstring", empty_field_cases)
def test_empty_param(bad_docstring):
    code = f"""
@external
def foo(a: int128):
    '''{bad_docstring}'''
    pass
    """
    with pytest.raises(NatSpecSyntaxException, match="No description given for parameter 'a'"):
        parse_natspec(code)


def test_too_many_returns_no_return_type():
    code = """
@external
def foo():
    '''@return should fail, the function does not include a return value'''
    pass
    """

    with pytest.raises(NatSpecSyntaxException, match="Method does not return any values"):
        parse_natspec(code)


def test_too_many_returns_single_return_type():
    code = """
@external
def foo() -> int128:
    '''
    @return int128
    @return this should fail
    '''
    return 1
    """

    with pytest.raises(
        NatSpecSyntaxException, match="Number of documented return values exceeds actual number"
    ):
        parse_natspec(code)


def test_too_many_returns_tuple_return_type():
    code = """
@external
def foo() -> (int128,uint256):
    '''
    @return int128
    @return uint256
    @return this should fail
    '''
    return 1, 2
    """

    with pytest.raises(
        NatSpecSyntaxException, match="Number of documented return values exceeds actual number"
    ):
        parse_natspec(code)
