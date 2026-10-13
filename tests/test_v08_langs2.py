"""v0.8 (G3): C, C++, Scala parser-lite slicers."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ghostslice.exporter import build_bundle, validate_bundle
from ghostslice.scanner import is_test_file, language_for, scan
from ghostslice.selection import symbols_for_source
from ghostslice.slicer import slice_source, slice_text

C_SAMPLE = """#include <stdio.h>
#include "store.h"
#define MAX_ITEMS 128

typedef unsigned long item_id;

struct Money {
    long cents;
    int currency;
};

enum Color { RED, GREEN, BLUE };

static int add_cents(struct Money *m, long delta) {
    m->cents += delta;
    if (delta > 0) {
        m->cents += 1;
    }
    return 0;
}

int total_cents(const struct Money *m);

void print_money(const struct Money *m) {
    printf("%ld\\n", m->cents);
}

int main(void) {
    return add_cents(0, 0);
}
"""

C_HEADER = """#ifndef STORE_H
#define STORE_H

struct Money {
    long cents;
    int currency;
};

int total_cents(const struct Money *m);
void print_money(const struct Money *m);
struct Money make_money(long cents);
long sum_all(const struct Money *items, int count);

#endif
"""

C_ADVERSARIAL = """#define OPEN {

static char closer = '}';

int uses_open(void) {
    return 1;
}

int tricky(void) {
#define LOCAL_OPEN {
    return 2;
}

char closer_fn(void) {
    return '}';
}

int after_all(void) {
    return 3;
}
"""

C_MACRO_MULTILINE = """#define WRAP(x) do { \\
    run(x); \\
} while (0)

int wrapped(void) {
    WRAP(1);
    return 1;
}

int after_macro(void) {
    return 5;
}
"""

C_STRIP = """int compute(void) { return 1; }

static void test_add_cents(void) {
    compute();
}

void testOther(void) {
    compute();
}

int real_work(void) {
    return compute();
}
"""

CPP_SAMPLE = """#include <string>
#include <vector>

namespace shop {

enum class Color { Red, Green };

struct Money {
    long cents;
};

template <typename T>
class Vec {
public:
    Vec() = default;
    void push(const T& item) {
        items_.push_back(item);
    }
    std::size_t size() const {
        return items_.size();
    }
private:
    std::vector<T> items_;
};

class Store {
public:
    explicit Store(std::string name) : name_(name) {}
    int total() const {
        const char *s = "}";
        return 42;
    }
    virtual ~Store() = default;
private:
    std::string name_;
    int total_ = 0;
};

template <typename T>
T identity(T value) {
    return value;
}

int helper(int x) {
    return x * 2;
}

}  // namespace shop

int main() {
    return shop::helper(21);
}
"""

CPP_ADVERSARIAL = r"""#include <string>

const char *json = R"({"a": [1, 2], "b": {"c": 3}})";

int big_number() {
    return 1'000'000;
}

char open_brace() {
    return '{';
}

std::string tricky() {
    auto s = R"raw(} "quoted" {)raw";
    return s;
}

int after_all() {
    return 7;
}
"""

CPP_STRIP = """#include "store.h"

int compute() { return 1; }

TEST(StoreTest, TotalWorks) {
    EXPECT_EQ(1, compute());
}

TEST_F(StoreFixture, Adds) {
    ASSERT_TRUE(true);
}

int real_work() { return compute(); }
"""

SCALA_SAMPLE = """package shop

import scala.collection.mutable.ListBuffer

trait Payer {
  def pay(cents: Int): Boolean
  def currency: String = "USD"
}

class Store(var name: String) {
  private var totalCents: Int = 0

  def total: Int = {
    val label = "}"
    totalCents
  }

  def add(cents: Int): Unit = {
    totalCents += cents
  }
}

object Store {
  def make(name: String): Store = new Store(name)
}

def formatPrice(cents: Int): String = {
  s"${cents / 100} dollars"
}

def afterAll: Int = 7
"""

SCALA3_SAMPLE = """package shop

class Counter:
  private var count: Int = 0

  def increment(step: Int): Unit =
    count += step

  def current: Int =
    count

def standalone(x: Int): Int =
  x * 2

class After:
  def value: Int = 5
"""

SCALA3_TRAIT = """package shop

trait Greeter:
  def greet(name: String): String

  def hello: String =
    greet("world")
"""

SCALA_ADVERSARIAL = r'''package shop

class Braces {
  val open: Char = '{'
  val tpl: String = s"value is ${Map("a" -> 1)}"

  /* outer /* nested } comment */ still } comment */
  def compute(x: Int): Int = {
    val s = """triple } quoted {"""
    x + 1
  }

  def after: Int = 9
}
'''

SCALA_STRIP = """class StoreSpec {
  def helper: Int = 1

  @Test
  def totalWorks(): Unit = {
    assert(total == 42)
  }

  def testLegacy(): Unit = {
    assert(true)
  }

  test("adds money") {
    assert(1 == 1)
  }

  def other: Int = 2
}
"""


class TestCSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(C_SAMPLE, "c", "signatures", path="store.c")
        self.assertIn("#include <stdio.h>", out)
        self.assertIn('#include "store.h"', out)
        self.assertIn("#define MAX_ITEMS 128", out)
        self.assertIn("typedef unsigned long item_id;", out)
        self.assertIn("struct Money {", out)
        self.assertIn("long cents;", out)
        self.assertIn("enum Color { RED, GREEN, BLUE };", out)
        self.assertIn("static int add_cents(struct Money *m, long delta)", out)
        self.assertIn("int total_cents(const struct Money *m);", out)
        self.assertIn("void print_money(const struct Money *m)", out)
        self.assertIn("int main(void)", out)
        self.assertNotIn("m->cents += delta", out)
        self.assertNotIn("printf", out)

    def test_interfaces(self):
        out = slice_source(C_SAMPLE, "c", "interfaces", path="store.c")
        self.assertIn("struct Money {", out)
        self.assertIn("enum Color", out)
        self.assertIn("typedef unsigned long item_id;", out)
        self.assertIn("#include <stdio.h>", out)
        self.assertNotIn("add_cents", out)
        self.assertNotIn("total_cents", out)
        self.assertNotIn("print_money", out)
        self.assertNotIn("main", out)

    def test_header_barely_shrinks_in_signatures(self):
        r = slice_text("store.h", C_HEADER, "signatures")
        self.assertIn("int total_cents(const struct Money *m);", r.text)
        self.assertIn("struct Money make_money(long cents);", r.text)
        self.assertGreaterEqual(r.sliced_tokens, int(0.8 * r.original_tokens))

    def test_strip_tests(self):
        out = slice_source(C_STRIP, "c", "strip-tests", path="store.c")
        self.assertIn("real_work", out)
        self.assertIn("compute", out)
        self.assertNotIn("test_add_cents", out)
        self.assertNotIn("testOther", out)

    def test_adversarial_macro_brace_and_char_literal(self):
        out = slice_source(C_ADVERSARIAL, "c", "signatures", path="x.c")
        for name in ("uses_open", "tricky", "closer_fn", "after_all"):
            self.assertIn(name, out)

    def test_adversarial_multiline_macro(self):
        # The multi-line macro definition is preprocessor surface and
        # is kept whole; its braces/backslashes must not break the
        # slicing of the functions around it.
        out = slice_source(C_MACRO_MULTILINE, "c", "signatures", path="x.c")
        self.assertIn("#define WRAP(x) do {", out)
        self.assertIn("int wrapped(void)", out)
        self.assertIn("int after_macro(void)", out)


class TestCppSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(CPP_SAMPLE, "cpp", "signatures", path="store.cpp")
        self.assertIn("#include <string>", out)
        self.assertIn("namespace shop {", out)
        self.assertIn("enum class Color { Red, Green };", out)
        self.assertIn("struct Money {", out)
        self.assertIn("template <typename T>", out)
        self.assertIn("class Vec {", out)
        self.assertIn("Vec() = default;", out)
        self.assertIn("void push(const T& item)", out)
        self.assertIn("std::size_t size() const", out)
        self.assertIn("std::vector<T> items_;", out)
        self.assertIn("class Store {", out)
        self.assertIn("explicit Store(std::string name)", out)
        self.assertIn("int total() const", out)
        self.assertIn("virtual ~Store() = default;", out)
        self.assertIn("std::string name_;", out)
        self.assertIn("int total_ = 0;", out)
        self.assertIn("T identity(T value)", out)
        self.assertIn("int helper(int x)", out)
        self.assertIn("int main()", out)
        self.assertNotIn("push_back", out)
        self.assertNotIn("return 42", out)

    def test_interfaces(self):
        out = slice_source(CPP_SAMPLE, "cpp", "interfaces", path="store.cpp")
        self.assertIn("enum class Color", out)
        self.assertIn("class Store {", out)
        self.assertIn("int total() const", out)
        self.assertIn("class Vec {", out)
        self.assertNotIn("identity", out)
        self.assertNotIn("helper", out)
        self.assertNotIn("int main()", out)

    def test_strip_tests_gtest(self):
        out = slice_source(CPP_STRIP, "cpp", "strip-tests", path="store.cpp")
        self.assertIn("real_work", out)
        self.assertIn("compute", out)
        self.assertNotIn("TotalWorks", out)
        self.assertNotIn("EXPECT_EQ", out)
        self.assertNotIn("StoreFixture", out)

    def test_adversarial_raw_strings_and_digit_separators(self):
        out = slice_source(CPP_ADVERSARIAL, "cpp", "signatures", path="x.cpp")
        for name in ("big_number", "open_brace", "tricky", "after_all"):
            self.assertIn(name, out)
        self.assertNotIn('"quoted"', out)


class TestScalaSlicer(unittest.TestCase):
    def test_signatures(self):
        out = slice_source(SCALA_SAMPLE, "scala", "signatures", path="Store.scala")
        self.assertIn("package shop", out)
        self.assertIn("import scala.collection.mutable.ListBuffer", out)
        self.assertIn("trait Payer {", out)
        self.assertIn("def pay(cents: Int): Boolean", out)
        self.assertIn('def currency: String = "USD"', out)
        self.assertIn("class Store(var name: String) {", out)
        self.assertIn("private var totalCents: Int = 0", out)
        self.assertIn("def total: Int", out)
        self.assertIn("def add(cents: Int): Unit", out)
        self.assertIn("object Store {", out)
        self.assertIn("def make(name: String): Store", out)
        self.assertIn("def formatPrice(cents: Int): String", out)
        self.assertIn("def afterAll: Int", out)
        self.assertNotIn("totalCents += cents", out)
        self.assertNotIn("dollars", out)

    def test_interfaces(self):
        out = slice_source(SCALA_SAMPLE, "scala", "interfaces", path="Store.scala")
        self.assertIn("trait Payer {", out)
        self.assertIn("def pay(cents: Int): Boolean", out)
        self.assertIn("class Store(var name: String) {", out)
        self.assertIn("def total: Int", out)
        self.assertNotIn("formatPrice", out)
        self.assertNotIn("afterAll", out)

    def test_scala3_indentation_style(self):
        out = slice_source(SCALA3_SAMPLE, "scala", "signatures", path="Counter.scala")
        self.assertIn("class Counter:", out)
        self.assertIn("private var count: Int = 0", out)
        self.assertIn("def increment(step: Int): Unit", out)
        self.assertIn("def current: Int", out)
        self.assertIn("def standalone(x: Int): Int", out)
        self.assertIn("class After:", out)
        self.assertIn("def value: Int", out)
        self.assertNotIn("count += step", out)
        self.assertNotIn("x * 2", out)

    def test_scala3_trait_kept_in_full(self):
        # Graceful degradation: an indented trait body is kept whole.
        out = slice_source(SCALA3_TRAIT, "scala", "signatures", path="G.scala")
        self.assertIn("trait Greeter:", out)
        self.assertIn("def greet(name: String): String", out)
        self.assertIn('greet("world")', out)

    def test_strip_tests(self):
        out = slice_source(SCALA_STRIP, "scala", "strip-tests", path="mixed.scala")
        self.assertIn("helper", out)
        self.assertIn("def other", out)
        self.assertNotIn("totalWorks", out)
        self.assertNotIn("testLegacy", out)
        self.assertNotIn("adds money", out)

    def test_adversarial_strings_comments_interpolation(self):
        out = slice_source(SCALA_ADVERSARIAL, "scala", "signatures", path="B.scala")
        self.assertIn("class Braces {", out)
        self.assertIn("def compute(x: Int): Int", out)
        self.assertIn("def after: Int", out)
        self.assertNotIn("x + 1", out)


class TestLangs2Wiring(unittest.TestCase):
    def test_language_detection(self):
        self.assertEqual(language_for("a.c"), "c")
        self.assertEqual(language_for("a.h"), "c")
        self.assertEqual(language_for("a.cpp"), "cpp")
        self.assertEqual(language_for("a.cc"), "cpp")
        self.assertEqual(language_for("a.cxx"), "cpp")
        self.assertEqual(language_for("a.hpp"), "cpp")
        self.assertEqual(language_for("a.hh"), "cpp")
        self.assertEqual(language_for("a.scala"), "scala")
        self.assertEqual(language_for("a.sc"), "scala")

    def test_test_file_conventions(self):
        self.assertTrue(is_test_file("store_test.cpp"))
        self.assertTrue(is_test_file("counter_test.cc"))
        self.assertTrue(is_test_file("thing_test.c"))
        self.assertTrue(is_test_file("StoreSpec.scala"))
        self.assertTrue(is_test_file("StoreSuite.scala"))
        self.assertTrue(is_test_file("StoreTest.scala"))
        self.assertFalse(is_test_file("latest.scala"))
        self.assertFalse(is_test_file("attest.scala"))
        self.assertFalse(is_test_file("contest.cpp"))

    def test_export_defaults_slice_new_languages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            root.mkdir()
            (root / "a.c").write_text(C_SAMPLE)
            (root / "b.cpp").write_text(CPP_SAMPLE)
            (root / "c.scala").write_text(SCALA_SAMPLE)
            out = Path(td) / "bundle"
            manifest = build_bundle(root, out, record_history=False)
            modes = {f["path"]: f["mode"] for f in manifest["files"]}
            for p in ("a.c", "b.cpp", "c.scala"):
                self.assertEqual(modes[p], "signatures")
            sliced = {f["path"]: f["sliced_tokens"] for f in manifest["files"]}
            original = {f["path"]: f["original_tokens"] for f in manifest["files"]}
            for p in sliced:
                self.assertLess(sliced[p], original[p])
            self.assertTrue(validate_bundle(out)["ok"])
            paths = {f.path for f in scan(root).files}
            self.assertEqual(paths, {"a.c", "b.cpp", "c.scala"})

    def test_symbols_flow_through_g2_path(self):
        c_syms = symbols_for_source("c", C_SAMPLE, path="store.c")
        self.assertIn("add_cents", c_syms)
        self.assertIn("Money", c_syms)
        cpp_syms = symbols_for_source("cpp", CPP_SAMPLE, path="store.cpp")
        self.assertIn("Store", cpp_syms)
        self.assertIn("total", cpp_syms)
        self.assertIn("helper", cpp_syms)
        sc_syms = symbols_for_source("scala", SCALA_SAMPLE, path="Store.scala")
        self.assertIn("Payer", sc_syms)
        self.assertIn("pay", sc_syms)
        self.assertIn("total", sc_syms)


if __name__ == "__main__":
    unittest.main()


CPP_OUT_OF_LINE = """Store::Store(std::string name)
    : name_(name), total_(0) {
}

int Store::total() const {
    return total_;
}

Store::~Store() {
}
"""

C_POINTER_RETURN = """struct Money *make_money(long cents) {
    return 0;
}

char *get_name(void) {
    return "x";
}

int plain(void) {
    return 1;
}
"""

CPP_ALLMAN_COMMENT = """class Foo // a comment; with semicolon
{
public:
    int bar() {
        return 1;
    }
};
"""

SCALA_TYPE_EQUALITY = """class Convert {
  def convert[A, B](a: A)(implicit ev: A =:= B): B = {
    a.asInstanceOf[B]
  }

  def after: Int = 1
}
"""


class TestAudit1Regressions(unittest.TestCase):
    def test_out_of_line_definitions_and_ctor_init_list(self):
        # F0 + F1: Class::method heads and multi-line ctor init lists.
        out = slice_source(CPP_OUT_OF_LINE, "cpp", "signatures", path="s.cpp")
        self.assertIn("Store::Store(std::string name)", out)
        self.assertIn(": name_(name), total_(0)", out)
        self.assertIn("int Store::total() const", out)
        self.assertIn("Store::~Store()", out)
        self.assertNotIn("return total_;", out)

    def test_pointer_attached_return_types(self):
        # F0: `struct Money *f(...)` and `char *f(...)` are heads.
        out = slice_source(C_POINTER_RETURN, "c", "signatures", path="m.c")
        self.assertIn("struct Money *make_money(long cents)", out)
        self.assertIn("char *get_name(void)", out)
        self.assertIn("int plain(void)", out)
        self.assertNotIn("return 0;", out)
        self.assertNotIn('return "x";', out)

    def test_allman_class_with_comment_semicolon(self):
        # F2: punctuation inside comments must not mislead the scans.
        out = slice_source(CPP_ALLMAN_COMMENT, "cpp", "signatures", path="f.cpp")
        self.assertIn("class Foo", out)
        self.assertIn("public:", out)
        self.assertIn("int bar()", out)
        self.assertIn("}", out)
        self.assertNotIn("return 1;", out)

    def test_scala_type_equality_not_body_equals(self):
        # F4: `=:=` in a signature is not the body `=`.
        out = slice_source(SCALA_TYPE_EQUALITY, "scala", "signatures",
                           path="c.scala")
        self.assertIn("def convert[A, B](a: A)(implicit ev: A =:= B): B", out)
        self.assertIn("def after: Int", out)
        self.assertNotIn("asInstanceOf", out)

    def test_symbols_for_out_of_line_and_pointer_heads(self):
        # F0 (selection side): the G2 regex reads the same shapes.
        cpp_syms = symbols_for_source("cpp", CPP_OUT_OF_LINE, path="s.cpp")
        self.assertIn("total", cpp_syms)
        c_syms = symbols_for_source("c", C_POINTER_RETURN, path="m.c")
        self.assertIn("make_money", c_syms)
        self.assertIn("get_name", c_syms)


CPP_SPLIT_DECLS = """class Shape {
public:
    virtual double area() const
        = 0;
    virtual ~Shape() = default;
};

int split_proto(int a)
    __attribute__((noreturn));

auto split_return(int a)
    -> int;
"""

CPP_GLOBALS = """Store global_store(5);
int y = compute(3);
unsigned mask = (1 << 3);

int real_fn(int a) {
    return a;
}
"""


class TestAudit2Regressions(unittest.TestCase):
    def test_split_declarations(self):
        # G1: a declaration whose `;` lands on a following line is a
        # prototype running to that line, not a dropped head plus a
        # stray continuation line.
        out = slice_source(CPP_SPLIT_DECLS, "cpp", "signatures", path="s.cpp")
        self.assertIn("virtual double area() const = 0;", out)
        self.assertIn("virtual ~Shape() = default;", out)
        self.assertIn("int split_proto(int a) __attribute__((noreturn));", out)
        self.assertIn("auto split_return(int a) -> int;", out)

    def test_globals_are_not_function_heads(self):
        # G2: the restructured head regex must not promote variable
        # declarations / initialisers to functions.
        out = slice_source(CPP_GLOBALS, "cpp", "signatures", path="g.cpp")
        self.assertIn("Store global_store(5);", out)
        self.assertIn("int y = compute(3);", out)
        self.assertIn("unsigned mask = (1 << 3);", out)
        self.assertIn("int real_fn(int a)", out)
        self.assertNotIn("return a;", out)
