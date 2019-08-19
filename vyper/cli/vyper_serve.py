#!/usr/bin/env python3

import argparse
from http.server import (
    BaseHTTPRequestHandler,
    HTTPServer,
)
import json
from socketserver import (
    ThreadingMixIn,
)

import vyper
from vyper.exceptions import (
    ParserException,
)
from vyper.parser import (
    lll_node,
)


def _parse_cli_args():
    parser = argparse.ArgumentParser(
        description='Serve Vyper compiler as an HTTP Service'
    )
    parser.add_argument('--version', action='version', version='{0}'.format(vyper.__version__))
    parser.add_argument(
        '-b',
        help='Address to bind JSON server on, default: localhost:8000',
        default='localhost:8000',
        dest='bind_address'
    )

    args = parser.parse_args()

    if ':' in args.bind_address:
        lll_node.VYPER_COLOR_OUTPUT = False
        runserver(*args.bind_address.split(':'))
    else:
        print('Provide bind address in "{address}:{port}" format')


class VyperRequestHandler(BaseHTTPRequestHandler):

    def send_404(self):
        self.send_response(404)
        self.end_headers()
        return

    def send_cors_all(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "X-Requested-With, Content-type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_all()
        self.end_headers()

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_cors_all()
            self.end_headers()
            self.wfile.write('Vyper Compiler. Version: {} \n'.format(vyper.__version__).encode())
        else:
            self.send_404()

        return

    def do_POST(self):

        if self.path == '/compile':
            content_len = int(self.headers.get('content-length'))
            post_body = self.rfile.read(content_len)
            data = json.loads(post_body)

            response, status_code = self._compile(data)

            self.send_response(status_code)
            self.send_header("Content-type", "application/json")
            self.send_cors_all()
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        else:
            self.send_404()

        return

    def _compile(self, data):
        code = data.get('code')
        if not code:
            return {'status': 'failed', 'message': 'No "code" key supplied'}, 400
        if not isinstance(code, str):
            return {'status': 'failed', 'message': '"code" must be a non-empty string'}, 400

        try:
            code = data['code']
            out_dict = vyper.compile_codes(
                {'': code},
                vyper.compiler.output_formats_map.keys(),
            )['']
            out_dict['ir'] = str(out_dict['ir'])
        except ParserException as e:
            return {
                'status': 'failed',
                'message': str(e),
                'column': e.col_offset,
                'line': e.lineno
            }, 400
        except SyntaxError as e:
            return {
                'status': 'failed',
                'message': str(e),
                'column': e.offset,
                'line': e.lineno
            }, 400

        out_dict.update({'status': "success"})

        return out_dict, 200


class VyperHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""
    pass


def runserver(host='', port=8000):
    server_address = (host, int(port))
    httpd = VyperHTTPServer(server_address, VyperRequestHandler)
    print('Listening on http://{0}:{1}'.format(host, port))
    httpd.serve_forever()
