"""Retry policy tests against a local mock HTTP server.

These tests exercise the real requests/urllib3 stack (no mocking of the
session) and count how often each request actually reaches the server.
No weclapp tenant is contacted.
"""
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import requests

from weclappy import Weclapp, WeclappAPIError


class _MockWeclappHandler(BaseHTTPRequestHandler):
    """Replies from a per-(method, path) script and counts every hit."""

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        server = self.server
        key = (self.command, self.path.split("?", 1)[0])
        with server.lock:
            server.hits[key] = server.hits.get(key, 0) + 1
            script = server.scripts.get(key, [])
            step = script.pop(0) if script else (200, {"ok": True}, {})
        status, body, headers = step
        if status == "sleep":
            time.sleep(body)
            status, body, headers = 200, {"ok": True}, {}
        payload = json.dumps(body).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = do_PUT = do_DELETE = _handle

    def log_message(self, format, *args):
        pass


class RetryPolicyTestBase(unittest.TestCase):
    client_kwargs = {}

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _MockWeclappHandler)
        cls.server.daemon_threads = True
        cls.server.lock = threading.Lock()
        cls.server.hits = {}
        cls.server.scripts = {}
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}/webapp/api/v1/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        with self.server.lock:
            self.server.hits.clear()
            self.server.scripts.clear()
        self.client = Weclapp(self.base_url, "test-key", **self.client_kwargs)

    def script(self, method, endpoint, *steps):
        self.server.scripts[(method, "/webapp/api/v1/" + endpoint)] = list(steps)

    def hits(self, method, endpoint):
        return self.server.hits.get((method, "/webapp/api/v1/" + endpoint), 0)


ERROR_500 = (500, {"error": "boom"}, {})
ERROR_429 = (429, {"error": "too many requests"}, {})


class TestDefaultRetryPolicy(RetryPolicyTestBase):

    # --- POST: never auto-retried on 5xx (possibly committed write) ---------

    def test_post_500_is_sent_exactly_once(self):
        self.script("POST", "salesOrder", ERROR_500)
        with self.assertRaises(WeclappAPIError) as ctx:
            self.client.post("salesOrder", {"customerId": "1"})
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(self.hits("POST", "salesOrder"), 1)

    def test_post_502_503_504_are_sent_exactly_once(self):
        for status in (502, 503, 504):
            with self.subTest(status=status):
                self.server.hits.clear()
                self.script("POST", "salesOrder", (status, {"error": "x"}, {}))
                with self.assertRaises(WeclappAPIError):
                    self.client.post("salesOrder", {"customerId": "1"})
                self.assertEqual(self.hits("POST", "salesOrder"), 1)

    def test_call_method_post_500_is_sent_exactly_once(self):
        endpoint = "salesOrder/id/42/createSalesInvoice"
        self.script("POST", endpoint, ERROR_500)
        with self.assertRaises(WeclappAPIError):
            self.client.call_method("salesOrder", "createSalesInvoice", "42", method="POST", data={})
        self.assertEqual(self.hits("POST", endpoint), 1)

    def test_post_read_timeout_is_not_retried(self):
        # Server accepted the request but the response did not arrive in time:
        # the write may be committed, so it must not be repeated blindly.
        self.script("POST", "salesOrder", ("sleep", 1.0, {}))
        with mock.patch("weclappy.DEFAULT_REQUEST_TIMEOUT", 0.3):
            with self.assertRaises(WeclappAPIError):
                self.client.post("salesOrder", {"customerId": "1"})
        self.assertEqual(self.hits("POST", "salesOrder"), 1)

    # --- POST: 429 is retried (request was rejected, not processed) ---------

    def test_post_429_is_retried(self):
        self.script("POST", "salesOrder", ERROR_429, ERROR_429)
        result = self.client.post("salesOrder", {"customerId": "1"})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.hits("POST", "salesOrder"), 3)

    def test_post_429_honours_retry_after(self):
        self.script("POST", "salesOrder", (429, {"error": "slow down"}, {"Retry-After": "1"}))
        start = time.monotonic()
        self.client.post("salesOrder", {"customerId": "1"})
        self.assertGreaterEqual(time.monotonic() - start, 0.9)
        self.assertEqual(self.hits("POST", "salesOrder"), 2)

    def test_post_429_retries_are_bounded(self):
        self.script("POST", "salesOrder", *([ERROR_429] * 10))
        with self.assertRaises(WeclappAPIError):
            self.client.post("salesOrder", {"customerId": "1"})
        self.assertEqual(self.hits("POST", "salesOrder"), 4)  # 1 + total=3

    # --- PUT / DELETE: same policy as POST ----------------------------------

    def test_put_500_is_sent_exactly_once(self):
        self.script("PUT", "salesOrder/id/42", ERROR_500)
        with self.assertRaises(WeclappAPIError):
            self.client.put("salesOrder", "42", {"version": "3"})
        self.assertEqual(self.hits("PUT", "salesOrder/id/42"), 1)

    def test_put_429_is_retried(self):
        self.script("PUT", "salesOrder/id/42", ERROR_429)
        self.client.put("salesOrder", "42", {"version": "3"})
        self.assertEqual(self.hits("PUT", "salesOrder/id/42"), 2)

    def test_delete_500_is_sent_exactly_once(self):
        self.script("DELETE", "salesOrder/id/42", ERROR_500)
        with self.assertRaises(WeclappAPIError):
            self.client.delete("salesOrder", "42")
        self.assertEqual(self.hits("DELETE", "salesOrder/id/42"), 1)

    def test_delete_429_is_retried(self):
        self.script("DELETE", "salesOrder/id/42", ERROR_429)
        self.client.delete("salesOrder", "42")
        self.assertEqual(self.hits("DELETE", "salesOrder/id/42"), 2)

    # --- GET: unchanged, 5xx and 429 are retried ----------------------------

    def test_get_500_is_retried(self):
        endpoint = "salesInvoice/id/7/downloadLatestSalesInvoicePdf"
        self.script("GET", endpoint, ERROR_500, ERROR_500)
        result = self.client.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", "7")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.hits("GET", endpoint), 3)

    def test_get_429_is_retried(self):
        endpoint = "salesInvoice/id/7/downloadLatestSalesInvoicePdf"
        self.script("GET", endpoint, ERROR_429)
        self.client.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", "7")
        self.assertEqual(self.hits("GET", endpoint), 2)

    def test_get_500_retries_are_bounded(self):
        endpoint = "salesInvoice/id/7/downloadLatestSalesInvoicePdf"
        self.script("GET", endpoint, *([ERROR_500] * 10))
        with self.assertRaises(WeclappAPIError):
            self.client.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", "7")
        self.assertEqual(self.hits("GET", endpoint), 4)

    def test_get_read_timeout_is_retried(self):
        endpoint = "salesInvoice/id/7/downloadLatestSalesInvoicePdf"
        self.script("GET", endpoint, ("sleep", 1.0, {}))
        with mock.patch("weclappy.DEFAULT_REQUEST_TIMEOUT", 0.3):
            self.client.call_method("salesInvoice", "downloadLatestSalesInvoicePdf", "7")
        self.assertEqual(self.hits("GET", endpoint), 2)


class TestWriteRetryOptIn(RetryPolicyTestBase):
    """retry_writes_on_server_error=True restores the pre-0.6.1 behaviour."""

    client_kwargs = {"retry_writes_on_server_error": True}

    def test_post_500_is_retried_when_opted_in(self):
        self.script("POST", "salesOrder", ERROR_500)
        self.client.post("salesOrder", {"customerId": "1"})
        self.assertEqual(self.hits("POST", "salesOrder"), 2)

    def test_put_500_is_retried_when_opted_in(self):
        self.script("PUT", "salesOrder/id/42", ERROR_500)
        self.client.put("salesOrder", "42", {"version": "3"})
        self.assertEqual(self.hits("PUT", "salesOrder/id/42"), 2)


if __name__ == "__main__":
    unittest.main()
