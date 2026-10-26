<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
<!--
*** Reference links are enclosed in brackets [ ] instead of parentheses ( ).
*** See the bottom of this document for the declaration of reference variables.
*** https://www.markdownguide.org/basic-syntax/#reference-style-links
-->

<div style="display:flex; justify-content: center;">

[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
</div>

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/gOps132/keep-or-nah">
    <img src="public/logo.png" alt="Logo" width="100" height="100">
  </a>

  <h3 align="center">Keep or Nah</h3>

  <p align="center">
    High-performance desktop photo triage and culling application for photographers.
    <br />
    <a href="https://github.com/gOps132/keep-or-nah"><strong>Explore the docs »</strong></a>
    <br />
    <br />
    <a href="https://github.com/gOps132/keep-or-nah/issues">Report Bug</a>
    &middot;
    <a href="https://github.com/gOps132/keep-or-nah/issues">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#key-features">Key Features</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#triage-workflow">Triage Workflow</a></li>
        <li><a href="#keyboard-shortcuts">Keyboard Shortcuts</a></li>
        <li><a href="#verification-pipeline">Verification Pipeline</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>

<!-- ABOUT THE PROJECT -->
## About The Project

Photographers often return from a shoot facing thousands of images: rapid-fire burst sequences, RAW + JPEG pairs, and XMP metadata sidecars. Existing photo management software is either bogged down by heavy database imports and catalog synchronizations, or limited to bare-bones file viewers that lack atomic file safety, high-speed inspection, and comparison tools.

**Keep or Nah** is an ultra-fast, focused desktop photo triage and culling application engineered to review, compare, and organize one **Photo Session** at a time. It treats same-stem files atomically, provides non-destructive staged decision-making with batch execution, synchronizes side-by-side frame comparisons, and automatically flags the sharpest shot in burst sequences—all backed by a transactional undo journal.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Key Features

* **Atomic File Pairing** — RAW, JPEG, and XMP sidecars share decisions and never get separated.
* **Rapid Keyboard Triage** — Triage in seconds with Keep (`D`), Nah (`A`), or Flag (`F`).
* **Staged Batch Commit** — Review decisions and reclaimed disk space before applying changes to disk.
* **Side-by-Side Comparison** — Synchronized 2-up zoom and pan with quick-pick keys (`1` and `2`).
* **Burst Detection & Best Shot** — Groups rapid bursts and badges the sharpest frame.
* **Safe Undo** — Transactional undo journal allows instant, verified reversals.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

<div style="display:flex;justify-content:center;">

[![Tauri][Tauri]][Tauri-url] [![Rust][Rust]][Rust-url] [![React][React.js]][React-url] [![TypeScript][TypeScript]][TypeScript-url] [![Vite][Vite]][Vite-url] [![Tailwind CSS][TailwindCSS]][Tailwind-url]
</div>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

To get a local development environment up and running, follow these simple steps.

### Prerequisites

* **Node.js** (v20 or higher) and **npm**
* **Rust** (stable toolchain with `cargo`)
  ```sh
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
  ```
* **Tauri System Dependencies** (Platform specific):
  * **macOS**: Xcode Command Line Tools (`xcode-select --install`)
  * **Linux**: `build-essential`, `libwebkit2gtk-4.1-dev`, `libappindicator3-dev`, `librsvg2-dev`
  * **Windows**: Microsoft Edge WebView2 and C++ Build Tools

### Download Pre-built App

Pre-compiled desktop releases are available on the [Releases page](https://github.com/gOps132/keep-or-nah/releases).

#### 🍎 macOS Gatekeeper Note
Because this open-source build is not signed with a paid Apple Developer Program certificate ($99/yr), macOS Gatekeeper quarantines downloaded files by default (displaying *"keep-or-nah is damaged and can't be opened"*).

To run the app:
1. Download **`Keep-or-Nah-macos-arm64.dmg`**, open it, and drag **`keep-or-nah`** into `/Applications`.
2. Open Terminal and run:
   ```bash
   xattr -cr /Applications/keep-or-nah.app
   ```
   *(Alternatively, go to **System Settings > Privacy & Security**, scroll down to the Security section, and click **Open Anyway**).*

---

### Installation from Source

1. Clone the repository:
   ```sh
   git clone https://github.com/gOps132/keep-or-nah.git
   cd keep-or-nah
   ```
2. Diagnose your local toolchain:
   ```sh
   scripts/agent/doctor.sh
   ```
3. Install frontend dependencies:
   ```sh
   npm --prefix frontend install
   ```
4. Start the application in development mode:
   ```sh
   npm run dev
   ```
5. Build the standalone desktop application executable:
   ```sh
   npm run build:app
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## Usage

### Triage Workflow

1. **Open a Photo Session**: Click **Open Folder** (or drag and drop a folder onto the window) to select a directory containing your photos. Keep or Nah natively scans the directory, groups same-stem files into **Photo Groups**, and populates the **Thumbnail Strip**.
2. **Make Triage Decisions**: Navigate through photos using the keyboard. For each Photo Group, assign:
   * **Keep** (`1`): Marks the group to be kept and routed to your designated keep destination (defaults to `<session>/keep`).
   * **Nah** (`2`): Marks the group to be discarded to the trash folder (defaults to `<session>/trash`).
   * **Flag** (`F`): Sets the group aside for later re-examination. In staged mode, it stays in place in the source folder; when using Immediate Mode with a **Flag Destination** configured in **Preferences**, it moves or copies the group to the chosen Flag folder.
3. **Compare Close Frames & Formats**: Press `C` to enter **Split Comparison** (`2-Up Compare`) mode. Pan and zoom simultaneously across both frames to inspect focus. Press `V` to cycle formats within a multi-format Photo Group (`RAW` + `JPG`), or press `X` in `2-Up` mode to compare `RAW` vs `JPG` side by side.
4. **Configure Destinations & Mode**: Open **Preferences** to customize default view mode (`1-Up` or `2-Up`), triage mode (`Staged Batch` or `Immediate Mode`), action mode (`Move` or `Copy`), custom **Keep**, **Nah**, and **Flag** destination folders, and representative format priority.
5. **Review and Batch Commit**: Click **Review Batch** (`⌘↵` / `Ctrl+Enter`) to inspect staged decisions, total photo counts, and disk space to be reclaimed, then choose **Move** or **Copy** and click **Commit**.
6. **Undo Anytime**: Made a mistake? Press `Cmd+Z` (`Ctrl+Z` on Windows/Linux) to reverse staged or immediate operations using the transactional **Undo Journal**.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Keyboard Shortcuts

Keep or Nah is designed for fluid, mouse-free triage:

| Key | Action |
| --- | --- |
| `Left` | Previous Photo Group |
| `Right` | Next Photo Group |
| `1` | Keep |
| `2` | Nah (discard) |
| `F` | Flag (set aside / route to Flag destination) |
| `C` | Toggle Split Comparison (`1-Up` / `2-Up`) |
| `V` | Cycle active file format within a multi-format Photo Group |
| `X` | Toggle between adjacent Photo Group comparison and intra-group Format Comparison in `2-Up` mode |
| `Cmd+Z` / `Ctrl+Z` | Undo last decision or file operation via Undo Journal |
| `Cmd+Enter` / `Ctrl+Enter` | Open Review & Batch Commit modal |
| `0` | Reset zoom and pan to fit |
| `Escape` | Close active modal |

*Note: Keyboard shortcuts are inactive while a modal dialog is open.*

### Debug Render Timing Log

To record every render boundary (`render.preview.fast`, `render.preview.full`, `render.thumbnail_decode`, `render.thumbnail_strip`, `render.split_comparison`, `render.loading_overlay`) with its `duration_ms` alongside user actions in thread-safe JSON Lines format:

```bash
KEEP_OR_NAH_DEBUG=1 KEEP_OR_NAH_DEBUG_LOG=/tmp/keep-or-nah-render.jsonl npm run dev
```

When `KEEP_OR_NAH_DEBUG` is unset, logging is completely disabled and writes no files.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Verification Pipeline

Keep or Nah maintains a strict verification gate. No work is complete without a green verification run:

```bash
# Full verification gate (doctor, formatting, lints, tests, build)
scripts/verify.sh

# Fast gate (skips packaging build)
scripts/verify.sh --fast

# List all pipeline stages
scripts/verify.sh --list
```

Per-role helper scripts:

| Script | Purpose |
| --- | --- |
| `scripts/agent/doctor.sh` | Diagnoses the local toolchain (`cargo`, `node`, `npm`, manifests) |
| `scripts/agent/lint.sh` | Runs `cargo fmt`, `cargo clippy -D warnings`, and frontend lint/typechecks |
| `scripts/agent/test.sh` | Runs Rust core & Tauri tests + frontend Vitest test suite |
| `scripts/agent/build.sh` | Builds the standalone desktop executable |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

- [x] Native Rust core engine (`keep_or_nah_core`) for high-throughput I/O
- [x] Atomic same-stem Photo Grouping (RAW + JPEG + XMP)
- [x] SIMD-accelerated Lanczos3 thumbnail and preview generation
- [x] Staged Triage with atomic Batch Commit and rollback safety
- [x] Split Comparison mode with synchronized 2-up pan and zoom
- [x] Burst Clustering via perceptual hashing (`dHash`) and Laplacian sharpness scoring
- [x] Transactional Undo Journal with identity verification
- [x] Cross-platform desktop release packaging via Tauri v2
- [ ] Color profile and HDR preview calibration

See the [open issues](https://github.com/gOps132/keep-or-nah/issues) for proposed features and active tracks.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Ensure the verification gate passes:
   ```sh
   scripts/verify.sh --fast
   ```
4. Commit your Changes using Conventional Commits (`git commit -m 'feat: add some amazing feature'`)
5. Push to the Branch (`git push origin feature/AmazingFeature`)
6. Open a Pull Request

### Top contributors:

<a href="https://github.com/gOps132/keep-or-nah/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=gOps132/keep-or-nah" alt="contrib.rocks image" />
</a>

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE` for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
## Contact

Project Link: [https://github.com/gOps132/keep-or-nah](https://github.com/gOps132/keep-or-nah)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* [Tauri](https://tauri.app/) — Lightweight, memory-efficient desktop application framework
* [fast_image_resize](https://github.com/Cykooz/fast_image_resize) — High-performance SIMD image resizing
* [kamadak-exif](https://github.com/kamadak/exif-rs) — Native EXIF parsing for Rust
* [Lucide Icons](https://lucide.dev/) — Clean, consistent icon system
* [Best-README-Template](https://github.com/othneildrew/Best-README-Template) — The foundational template for this README

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
<!-- https://www.markdownguide.org/basic-syntax/#reference-style-links -->
[contributors-shield]: https://img.shields.io/github/contributors/gOps132/keep-or-nah.svg?style=for-the-badge
[contributors-url]: https://github.com/gOps132/keep-or-nah/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/gOps132/keep-or-nah.svg?style=for-the-badge
[forks-url]: https://github.com/gOps132/keep-or-nah/network/members
[stars-shield]: https://img.shields.io/github/stars/gOps132/keep-or-nah.svg?style=for-the-badge
[stars-url]: https://github.com/gOps132/keep-or-nah/stargazers
[issues-shield]: https://img.shields.io/github/issues/gOps132/keep-or-nah.svg?style=for-the-badge
[issues-url]: https://github.com/gOps132/keep-or-nah/issues
[license-shield]: https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge
[license-url]: https://github.com/gOps132/keep-or-nah
[Tauri]: https://img.shields.io/badge/Tauri-24C8D8?style=for-the-badge&logo=tauri&logoColor=white
[Tauri-url]: https://tauri.app/
[Rust]: https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white
[Rust-url]: https://www.rust-lang.org/
[React.js]: https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[React-url]: https://reactjs.org/
[TypeScript]: https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white
[TypeScript-url]: https://www.typescriptlang.org/
[Vite]: https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white
[Vite-url]: https://vitejs.dev/
[TailwindCSS]: https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white
[Tailwind-url]: https://tailwindcss.com/
