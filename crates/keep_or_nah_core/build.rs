//! Build script for the native core.
//!
//! A Python extension module is a shared object that leaves the CPython
//! symbols unresolved: the host interpreter provides them when the module is
//! imported. The macOS linker refuses to produce such a shared object by
//! default, so the undefined symbols have to be allowed explicitly.
//!
//! Maturin passes exactly these flags when it builds a wheel. Emitting them
//! here as well means a plain `cargo build` produces the same kind of object,
//! instead of failing with "undefined symbols: __Py_FalseStruct,
//! __Py_NoneStruct, __Py_TrueStruct".
//!
//! The flags are scoped to `cdylib` targets on purpose: a test binary is an
//! executable, and an executable has to resolve every symbol at link time.

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os != "macos" {
        return;
    }

    println!("cargo:rustc-link-arg-cdylib=-undefined");
    println!("cargo:rustc-link-arg-cdylib=dynamic_lookup");
}
