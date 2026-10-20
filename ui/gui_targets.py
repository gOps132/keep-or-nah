"""Late-bound access to the names the composition root publishes.

`gui_app` is the composition root of the desktop GUI: it imports the mixins
that make up this package. A mixin therefore cannot import `gui_app` at
module scope without creating an import cycle.

`gui_app` also publishes a few module-level names — `Image`, `ImageTk`, and
`thumbnail_rgba` — that the test suite patches by name. Code that moved into
this package has to resolve those names through the module object at call
time; binding them at import scope would leave the patched names behind and
the patch would silently stop reaching the code it was written for.

`gui_module()` answers both requirements with one call.
"""

from __future__ import annotations

import importlib
from types import ModuleType


def gui_module() -> ModuleType:
    """Return the imported `gui_app` module."""
    return importlib.import_module("gui_app")
