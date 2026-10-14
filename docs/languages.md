# Languages

Part of the [GhostSlice README](../README.md). The parser-lite language set beyond Python and TypeScript/JavaScript.

## More languages (v0.3, v0.5, v0.8)

Go, Rust, Java, and C# joined Python and TypeScript/JavaScript in
v0.3, with parser-lite `signatures` and `interfaces` modes and test
stripping (Go `TestXxx` functions, Rust `#[test]` / `mod tests`, Java
`@Test`, C# `[Test]` / `[Fact]`).

v0.5 adds PHP, Ruby, Kotlin, and Swift, same parser-lite label:

| Language | signatures / interfaces keep | strip-tests drops |
|---|---|---|
| PHP | functions, classes, interfaces, traits, enums, properties | `test*` methods, `/** @test */` docblock methods, `#[Test]` methods |
| Ruby | `def` signatures, `class`/`module` blocks, `attr_*`, constants | `def test_*`, `describe`/`context`/`it` blocks |
| Kotlin | `fun`, `class`/`interface`/`object`, `val`/`var` | `@Test` functions, `test*` functions |
| Swift | `func`, `class`/`struct`/`protocol`/`enum`/`extension`, `var`/`let` | `test*` XCTest-style functions, `@Test` functions |

Ruby blocks are tracked by keyword/`end` matching (no braces); the
others reuse the string/comment-aware brace matcher. Parser-lite
honesty applies: conventional formatting slices well, exotic syntax
may not.

Kotlin note (v1.0.6): primary-constructor properties are symbols.
A `val`/`var` parameter of a primary constructor — in a data class
or a plain class, one-line or multi-line head — is a member
property of the class for outlines, `slice --symbols`, signatures,
and task selection (a parameter without `val`/`var` is not a
member and is not listed). Multi-line constructor heads outline
and slice with their true spans; before v1.0.6 the class span
truncated to the declaration line and the parameters leaked into
outlines as parentless top-level properties.

v0.8 adds C, C++, and Scala, same parser-lite label:

| Language | signatures / interfaces keep | strip-tests drops |
|---|---|---|
| C | `#include` and other preprocessor lines, function signatures/prototypes, struct/union/enum blocks, typedefs | `test_*` / `testXxx` functions |
| C++ | the C surface plus classes (member signatures), namespaces, templates, enum class | gtest `TEST`/`TEST_F`/`TEST_P` blocks, `test_*` functions |
| Scala | `def` signatures, `val`/`var`, class/object declarations, trait/enum in full | `@Test` defs, `test_*` defs, `test("...") { }` blocks |

C details: interfaces mode keeps the type surface (struct/union/
enum/typedef, preprocessor) and drops free functions; a `.h` header
of prototypes barely shrinks in signatures mode, which is correct —
it is already all surface. `.h` is treated as C by convention (C++
headers use `.hpp`/`.hh`); a C++ class in a `.h` file slices by the
C rules and loses its class context. The brace matcher now also
skips preprocessor lines (macro braces cannot corrupt it), consumes
C++ raw strings whole, and treats `1'000'000` digit separators and
`'{'` char literals correctly. C++ out-of-line definitions
(`int Store::total() const`) and constructor initializer lists are
supported. Scala details: block comments nest, triple-quoted
strings and `s"..."` interpolation are honoured, and Scala 3
significant-indentation bodies are handled by an indentation
fallback that degrades to keeping more (an indented trait is kept
in full), never less. Known lite limits for the three: K&R
parameter declarations (read as a prototype), one-line class
bodies, `extern "C"` wrappers, C++ concepts/requires clauses,
Scala `given` instances and extension methods.
