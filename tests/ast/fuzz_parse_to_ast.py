import sys

import atheris

with atheris.instrument_imports():
    from vyper.ast import parse_to_ast
    from vyper.exceptions import SyntaxException, ParserException, SyntaxException

def TestOneInput(data):
    fdp = atheris.FuzzedDataProvider(data)
    try:
        _ = parse_to_ast(fdp.ConsumeString(len(data)))
    except SyntaxException:
        None
    except ValueError:
        None
    except IndentationError:
        None
    except ParserException:
        None
    except SyntaxException:
        None



def main():
    atheris.Setup(sys.argv, TestOneInput, enable_python_coverage=True)
    atheris.Fuzz()

if __name__ == "__main__":
    main()
