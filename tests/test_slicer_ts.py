import unittest

from ghostslice.slicer import slice_source, slice_text

TS = '''import { readFile } from "fs";

export interface User {
  id: number;
  name: string;
}

export type UserId = string;

export const VERSION = "1.0.0";

export function loadUser(id: UserId): User {
  const secretBodyMarker = readFile(id);
  return { id: 1, name: String(secretBodyMarker) };
}

export const formatName = (user: User): string => {
  const upperMarker = user.name.toUpperCase();
  return upperMarker;
};

export class Store {
  private cache: Map<string, string>;
  constructor() {
    this.cache = new Map();
  }
  get(key: string): string {
    const hitMarker = this.cache.get(key);
    return hitMarker || "";
  }
  put(key: string, value: string): void {
    this.cache.set(key, value);
  }
}

describe("Store", () => {
  it("stores values", () => {
    const s = new Store();
    s.put("a", "b");
  });
});
'''


class TestTypeScriptSlicer(unittest.TestCase):
    def test_full_is_identical(self):
        self.assertEqual(slice_source(TS, "typescript", "full", "m.ts"), TS)

    def test_exclude_is_empty(self):
        self.assertEqual(slice_source(TS, "typescript", "exclude", "m.ts"), "")

    def test_signatures(self):
        out = slice_source(TS, "typescript", "signatures", "m.ts")
        self.assertIn("interface User", out)
        self.assertIn("type UserId = string;", out)
        self.assertIn("function loadUser(id: UserId): User", out)
        self.assertIn("formatName", out)
        self.assertIn("class Store", out)
        self.assertIn("get(key: string)", out)
        self.assertNotIn("secretBodyMarker", out)
        self.assertNotIn("upperMarker", out)
        self.assertNotIn("hitMarker", out)

    def test_signatures_smaller(self):
        r = slice_text("m.ts", TS, "signatures")
        self.assertLess(r.sliced_tokens, r.original_tokens)

    def test_interfaces_only_types(self):
        out = slice_source(TS, "typescript", "interfaces", "m.ts")
        self.assertIn("interface User", out)
        self.assertIn("name: string;", out)
        self.assertIn("type UserId = string;", out)
        self.assertNotIn("loadUser", out)
        self.assertNotIn("class Store", out)
        self.assertNotIn("secretBodyMarker", out)

    def test_strip_tests(self):
        out = slice_source(TS, "typescript", "strip-tests", "m.ts")
        self.assertIn("loadUser", out)
        self.assertIn("secretBodyMarker", out)  # bodies preserved in strip-tests
        self.assertNotIn("describe", out)
        self.assertNotIn("stores values", out)

    def test_strip_tests_on_test_file_is_empty(self):
        out = slice_source(TS, "typescript", "strip-tests", "src/store.test.ts")
        self.assertEqual(out, "")

    def test_object_default_params_and_method_bodies(self):
        src = (
            "function emptyState(workspace = {}) {\n"
            "  return { agents: [], secretInner: workspace };\n"
            "}\n"
            "export class Bus {\n"
            "  _event(type, meta = {}) {\n"
            "    for (const fn of this.listeners) { fn(meta); }\n"
            "  }\n"
            "}\n"
        )
        out = slice_source(src, "javascript", "signatures", "b.js")
        self.assertIn("function emptyState(workspace = {})", out)
        self.assertIn("_event(type, meta = {})", out)
        self.assertNotIn("secretInner", out)
        self.assertNotIn("for (const fn", out)

    def test_javascript_language_also_slices(self):
        out = slice_source(TS, "javascript", "signatures", "m.js")
        self.assertIn("function loadUser", out)
        self.assertNotIn("secretBodyMarker", out)


if __name__ == "__main__":
    unittest.main()
