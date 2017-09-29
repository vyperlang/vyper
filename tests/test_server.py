import pytest
import json

from io import BytesIO as IO

from viper.server import ViperRequestHandler


def make_json_request(method, path, payload=""):
    if payload:
        payload = json.dumps(payload)

    raw_request = """{method} {path} HTTP/1.1
Content-Length: {length}

{payload}""".format(
        method=method.upper(),
        path=path,
        length=len(payload),
        payload=payload
    )

    class MockRequest(object):
        def __init__(self):
            self.write_output = IO()

        def makefile(self, *args, **kwargs):
            return IO(raw_request.encode())

        def sendall(self, b):
            self.write_output.write(b)

    class MockServer(object):
        def __init__(self, ip_port, Handler):
            self.fake_handler = Handler(MockRequest(), ip_port, self)

    server = MockServer(('', 0), ViperRequestHandler)

    request = server.fake_handler.request

    request.write_output.seek(0)
    response = request.write_output.read().decode()
    fields = response.split("\r\n")

    headers = fields[:-1]

    return headers, json.loads(''.join(fields[-1]))


def test_compile_request():
    payload = {
        "code": "\ndef test() -> num:\n    return 1\n"
    }
    headers, output = make_json_request('POST', '/compile', payload)

    assert "200" in headers[0]
    assert output['abi'] == [{'name': 'test', 'outputs': [{'type': 'int128', 'name': 'out'}], 'inputs': [], 'constant': False, 'payable': False, 'type': 'function'}]  # noqa
