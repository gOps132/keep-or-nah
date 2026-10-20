# The Native Core Is Built for CPython's Stable ABI

The native core is a PyO3 extension module. We decided to build it against CPython's stable ABI (`abi3-py312`) rather than against one specific CPython version, so that the Rust unit tests can run on a machine with no Python installation at all, and so that the published wheel is not tied to a single interpreter build.

## Considered Options

- **Version-specific build** (`pyo3` with no `abi3` feature, linking `libpython3.12`): the traditional PyO3 setup. The test harness then has to link against a real libpython, which means the Rust suite cannot run without a Python development install — and the build breaks on any machine where the interpreter's shared library is not where PyO3 expects it. It also produces a wheel that only installs on one CPython minor version.
- **Stable ABI with the floor at the oldest supported Python** (`abi3-py37`): the same benefit as below, but it tags the wheel `cp37-abi3`, which claims compatibility with CPython 3.7 through 3.11. The application declares `requires-python = ">=3.12,<3.14"` and has never been tested on those interpreters, so the artifact would promise support the project does not offer.
- **Stable ABI with the floor at the project's minimum supported Python** (`abi3-py312`, Chosen): the Rust suite runs with no interpreter present, and the wheel tag `cp312-abi3` matches the application's own `requires-python`. The artifact promises exactly the range the project supports.

## Consequences

- The Rust test suite runs with `PYO3_NO_PYTHON=1 cargo test --no-default-features` and needs no interpreter, no libpython, and no development headers. It runs identically on a developer laptop and on a CI runner.
- The crate's `extension-module` feature is a cargo feature, not a hard-coded dependency feature, so the test harness can be built with it off. A `[dev-dependencies]` entry on `pyo3` with `extension-module` is what makes the test binary link without libpython: Cargo unifies the two for the test target only, and the release build maturin drives never sees the dev-dependency.
- The crate needs a `build.rs` that adds `-undefined dynamic_lookup` for `cdylib` targets on macOS. A Python extension module leaves the CPython symbols unresolved for the host interpreter to provide, and the macOS linker refuses to produce such an object by default. Maturin passes these flags itself; the build script makes a plain `cargo build` produce the same kind of object instead of failing with `undefined symbols: __Py_FalseStruct`.
- The published wheel is tagged `cp312-abi3` rather than `cp312-cp312`. The binary is a different artifact from the one a version-specific build produces, and the tag describes it honestly.
- The stable ABI is a different calling convention from the version-specific one: CPython resolves it through a function-pointer table rather than direct symbol access. The cost is a small amount of overhead per Python call, which is irrelevant here because the hot paths are Rust, not Python.
- If the project's minimum supported Python is ever raised, the `abi3` floor has to be raised with it. The two values are linked and a mismatch between them is a packaging bug, not a cosmetic difference.
