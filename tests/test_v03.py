import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.mcp_server import handle_message
from ghostslice.slicer import slice_source, slice_text

GO_SAMPLE = """package shop

import "fmt"

type Item struct {
	Name  string
	Price int
}

type Store interface {
	Buy(id int) error
}

func (s *Shop) Total() int {
	total := 0
	fmt.Println("counting")
	return total
}

func Add(a int, b int) int {
	return a + b
}
"""

GO_TEST = """package shop

func helper() int { return 1 }

func TestAdd(t *testing.T) {
	if Add(1, 2) != 3 {
		t.Fail()
	}
}
"""

RUST_SAMPLE = """use std::fmt;

pub struct Point {
    pub x: i32,
    pub y: i32,
}

pub trait Shape {
    fn area(&self) -> i32;
}

impl Point {
    pub fn new(x: i32, y: i32) -> Self {
        let p = Self { x, y };
        p
    }
}

pub fn distance(a: &Point, b: &Point) -> i32 {
    let dx = a.x - b.x;
    dx.abs()
}
"""

RUST_TEST = """pub fn keep() -> i32 { 1 }

#[cfg(test)]
mod tests {
    #[test]
    fn it_works() {
        assert_eq!(1, 1);
    }
}
"""

JAVA_SAMPLE = """package shop;

import java.util.List;

public class Store {
    private int total;

    public int total() {
        int x = compute();
        return x;
    }

    private int compute() {
        return 42;
    }
}

interface Payer {
    boolean pay(int cents);
}
"""

JAVA_TEST = """package shop;

public class StoreTest {
    @Test
    public void totalWorks() {
        assertTrue(true);
    }

    public void helper() {
    }
}
"""

CSHARP_SAMPLE = """using System;

namespace Shop {
    public class Store {
        private int total;

        public int Total() {
            var x = Compute();
            return x;
        }

        private int Compute() {
            return 42;
        }
    }

    public interface IPayer {
        bool Pay(int cents);
    }
}
"""


class TestGoSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(GO_SAMPLE, "go", "signatures", path="shop.go")
        self.assertIn("type Item struct", out)
        self.assertIn("func (s *Shop) Total() int", out)
        self.assertIn("func Add(a int, b int) int", out)
        self.assertNotIn("counting", out)
        self.assertNotIn("return a + b", out)

    def test_interfaces(self):
        out = slice_source(GO_SAMPLE, "go", "interfaces", path="shop.go")
        self.assertIn("type Store interface", out)
        self.assertIn("Buy(id int) error", out)
        self.assertNotIn("func Add", out)

    def test_strip_tests(self):
        # GO_TEST content lives in a non-test file here, so only the
        # TestXxx function is stripped (a real *_test.go file slices to
        # empty by the generic test-file rule).
        out = slice_source(GO_TEST, "go", "strip-tests", path="shop.go")
        self.assertIn("func helper()", out)
        self.assertNotIn("TestAdd", out)


class TestRustSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(RUST_SAMPLE, "rust", "signatures", path="lib.rs")
        self.assertIn("pub struct Point", out)
        self.assertIn("pub trait Shape", out)
        self.assertIn("pub fn new(x: i32, y: i32) -> Self", out)
        self.assertIn("pub fn distance", out)
        self.assertNotIn("dx.abs()", out)

    def test_interfaces(self):
        out = slice_source(RUST_SAMPLE, "rust", "interfaces", path="lib.rs")
        self.assertIn("pub trait Shape", out)
        self.assertIn("fn area(&self) -> i32;", out)
        self.assertNotIn("pub fn distance", out)

    def test_strip_tests_mod(self):
        out = slice_source(RUST_TEST, "rust", "strip-tests", path="lib.rs")
        self.assertIn("pub fn keep()", out)
        self.assertNotIn("it_works", out)


class TestJavaSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(JAVA_SAMPLE, "java", "signatures", path="Store.java")
        self.assertIn("public class Store", out)
        self.assertIn("public int total()", out)
        self.assertIn("interface Payer", out)
        self.assertNotIn("return 42", out)
        self.assertNotIn("int x = compute()", out)

    def test_strip_tests(self):
        # @Test method inside a regular source file: only it is stripped.
        out = slice_source(JAVA_TEST, "java", "strip-tests", path="Checks.java")
        self.assertIn("public void helper()", out)
        self.assertNotIn("totalWorks", out)


class TestCSharpSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(CSHARP_SAMPLE, "csharp", "signatures", path="Store.cs")
        self.assertIn("public class Store", out)
        self.assertIn("public int Total()", out)
        self.assertIn("public interface IPayer", out)
        self.assertNotIn("return 42", out)


class TestMCPHandle(unittest.TestCase):
    def test_initialize_and_tools_list(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(resp["result"]["serverInfo"]["name"], "ghostslice")
        resp = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        self.assertEqual(names, {"scan_project", "slice_file", "estimate_cost", "export_bundle", "check_secrets", "lint_project"})

    def test_unknown_method_errors(self):
        resp = handle_message({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        self.assertEqual(resp["error"]["code"], -32601)

    def test_notification_gets_no_response(self):
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))


class TestMCPStdio(unittest.TestCase):
    def test_stdio_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "app.py").write_text("def main():\n    print('x')\n" * 5)
            env = dict(os.environ)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            proc = subprocess.Popen(
                [sys.executable, "-m", "ghostslice", "mcp"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                text=True, env=env)
            try:
                msgs = [
                    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "scan_project", "arguments": {"path": td}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "slice_file", "arguments":
                                {"path": td, "file": "app.py", "mode": "signatures"}}},
                    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                     "params": {"name": "estimate_cost", "arguments": {"path": td}}},
                    {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                     "params": {"name": "export_bundle", "arguments":
                                {"path": td, "out": str(root / "bundle")}}},
                ]
                inp = "\n".join(json.dumps(m) for m in msgs) + "\n"
                out, _ = proc.communicate(inp, timeout=60)
            finally:
                if proc.poll() is None:
                    proc.kill()
            by_id = {}
            for line in out.splitlines():
                d = json.loads(line)
                by_id[d["id"]] = d
            self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "ghostslice")
            self.assertEqual(len(by_id[2]["result"]["tools"]), 6)
            scan_payload = json.loads(by_id[3]["result"]["content"][0]["text"])
            self.assertEqual(scan_payload["file_count"], 1)
            slice_payload = json.loads(by_id[4]["result"]["content"][0]["text"])
            self.assertIn("def main(", slice_payload["text"])
            self.assertNotIn("print", slice_payload["text"])
            cost_payload = json.loads(by_id[5]["result"]["content"][0]["text"])
            self.assertIn("after_cost_usd", cost_payload)
            export_payload = json.loads(by_id[6]["result"]["content"][0]["text"])
            self.assertGreater(export_payload["total_saved_tokens"], 0)
            self.assertTrue((root / "bundle" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
