"""The `ui` package: the decomposed parts of the desktop GUI.

`gui_app.py` is the composition root: it owns the `App` class, the widget
tree, and the application state. Everything that is not state or wiring
lives here, one cohesive concern per module:

| Module                  | Responsibility                                        |
| ----------------------- | ----------------------------------------------------- |
| `preview_controller`    | Preview rendering, texture caching, loading overlay   |
| `compare_controller`    | Split Comparison and the action buttons               |
| `thumbnail_strip`       | The Thumbnail Strip and its decoding worker           |
| `shortcuts`             | Keyboard bindings and their handlers                  |
| `viewport`              | Zoom, pan, and viewport centering                     |
| `layout`                | Construction of the `App` widget tree                 |
| `settings_dialog`       | The Preview Settings dialog                           |
| `session_commands`      | Commands that act on the photo session                |
| `gui_targets`           | Late-bound access to the names `gui_app` publishes    |

Every module in this package is a mixin: its methods operate on `self`,
which is the `App`. The `App` therefore stays the single owner of the widget
tree, because a Tk widget has exactly one parent.
"""
