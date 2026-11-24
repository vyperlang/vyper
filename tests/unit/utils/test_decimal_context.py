import decimal
import threading

from tests.utils import parse_and_fold


def test_decimal_precision_in_worker_thread():
    # decimal contexts are thread-local; threads other than the one which
    # imported vyper must also evaluate decimals at full precision, not
    # the stdlib default of 28 significant digits
    results = {}

    def fold():
        try:
            vyper_ast = parse_and_fold("12345678901234567890.1234567890 + 0.0000000001")
            results["value"] = vyper_ast.body[0].value.get_folded_value().value
        except Exception as e:  # pragma: nocover
            results["error"] = e

    t = threading.Thread(target=fold)
    t.start()
    t.join()

    assert "error" not in results, results.get("error")
    assert results["value"] == decimal.Decimal("12345678901234567890.1234567891")
