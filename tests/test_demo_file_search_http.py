"""The demo must accept the actual recursive-search payload from the web UI."""
from http.server import ThreadingHTTPServer
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from titan.server import Application, Handler


class DemoFileSearchHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = Application(self.temporary.name, demo=True)
        self.document = self.app.agent.directory / "Dokumente/Budget.csv"
        self.content = "Posten;Euro\nSpeicher;120\n".encode()
        self.document.write_bytes(self.content)
        os.utime(self.document, (1700000000, 1700000000))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.app.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.app.agent._temporary.cleanup()
        self.temporary.cleanup()

    def request(self, path, query):
        request = urllib.request.Request(self.url + path + "?" + urllib.parse.urlencode(query))
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as response:
            return response.code, response.read()

    def search(self, **extras):
        status, raw = self.request("/api/files", {
            "share": "dokumente", "path": "", "offset": "0", "limit": "200",
            "search": "Budget", **extras,
        })
        return status, json.loads(raw)

    def test_mobile_search_query_finds_and_opens_real_nested_budget_file(self):
        status, result = self.search(recursive="1")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["entries"][0]["path"], "Dokumente/Budget.csv")
        self.assertEqual(result["entries"][0]["name"], "Budget.csv")
        status, raw = self.request("/api/file", {"share": "dokumente", "path": result["entries"][0]["path"]})
        self.assertEqual((status, raw), (200, self.content))
        self.assertEqual(self.search()[1]["total"], 0, "Ordinary folder search must not silently recurse.")

    def test_all_production_search_filters_are_accepted_and_applied_in_demo(self):
        status, result = self.search(recursive="1", type="document", min_size="1", max_size="100",
                                     modified_after="1700000000", modified_before="1700000000")
        self.assertEqual(status, 200, result)
        self.assertEqual([entry["path"] for entry in result["entries"]], ["Dokumente/Budget.csv"])
        for filters in ({"type": "image"}, {"min_size": "1000"}, {"modified_after": "1700000001"}):
            with self.subTest(filters=filters):
                status, result = self.search(recursive="1", **filters)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["total"], 0)

    def test_invalid_recursive_and_filter_queries_still_fail_before_listing(self):
        for filters in ({"recursive": "on"}, {"recursive": "1", "type": "executable"},
                        {"recursive": "1", "min_size": "-1"}):
            with self.subTest(filters=filters):
                status, result = self.search(**filters)
                self.assertEqual(status, 400, result)


if __name__ == "__main__":
    unittest.main()
