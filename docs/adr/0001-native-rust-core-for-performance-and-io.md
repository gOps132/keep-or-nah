# Native Rust Core for I/O, Decoding, and Image Analysis

Desktop photo culling requires instantaneous directory scanning, SIMD thumbnail generation, atomic multi-file moves with transactional undo, and real-time sharpness/hash calculation without freezing the GUI. We decided to implement performance-critical directory traversal, file operations, Lanczos3 thumbnail generation, and blur/burst analysis in a native Rust crate (`keep_or_nah_core`) bound to Python via PyO3, maintaining Python strictly for GUI orchestration and session flow.

## Considered Options

- **Pure Python (Pillow + standard library `shutil`)**: Inadequate decode and filter performance on large 24MP+ photo queues, leading to dropped frames and main-thread blocking, with no transactional rollback guarantees for interrupted file moves.
- **C/C++ Extensions or OpenCV**: Higher build and cross-compilation complexity with heavyweight shared library runtimes.
- **Native Rust Crate via PyO3 / Maturin (Chosen)**: Memory safety, SIMD-accelerated image scaling, zero-cost concurrency releasing the Python GIL, and single-binary distribution.

## Consequences

- Requires the Rust toolchain (`cargo`, `maturin`) for development builds.
- Releases the Python GIL during heavy I/O and matrix computations, keeping the UI responsive.
