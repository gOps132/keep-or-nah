import unittest
from unittest.mock import Mock

import main
from gui_app import App


class UnifiedBootTests(unittest.TestCase):
    def test_main_boots_unified_gui_app_frontend(self):
        app_class = main.resolve_app_class()

        self.assertIs(app_class, App)

    def test_main_runs_the_unified_app(self):
        with patch_gui_app("gui_app", main) as gui_module:
            main.main()

            gui_module.App.assert_called_once_with()
            gui_module.App.return_value.mainloop.assert_called_once_with()


class UnifiedKeyboardShortcutTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(App)
        self.app.bind_all = Mock()
        self.app.bind = Mock()

    def bound_sequences(self):
        bound = [call.args[0] for call in self.app.bind_all.call_args_list]
        bound += [call.args[0] for call in self.app.bind.call_args_list]
        return bound

    def test_primary_navigation_shortcuts_are_bound(self):
        self.app.bind_shortcuts()

        bound = self.bound_sequences()
        for sequence in ("<Left>", "<Right>", "<KeyPress-a>", "<KeyPress-d>"):
            self.assertIn(sequence, bound)

    def test_space_and_delete_drive_keep_and_nah_decisions(self):
        self.app.bind_shortcuts()

        bound = self.bound_sequences()
        self.assertIn("<space>", bound)
        self.assertIn("<Delete>", bound)

        self.app.sort_current_photo = Mock()
        self.app.shortcuts_enabled = Mock(return_value=True)

        self.app.handle_space_shortcut()
        self.app.sort_current_photo.assert_called_once_with("keep")

        self.app.handle_delete_shortcut()
        self.assertEqual(self.app.sort_current_photo.call_count, 2)
        self.app.sort_current_photo.assert_called_with("nah")

    def test_undo_shortcut_is_bound_with_platform_modifier(self):
        import sys

        self.app.bind_shortcuts()

        bound = self.bound_sequences()
        modifier = "Command" if sys.platform == "darwin" else "Control"
        self.assertIn(f"<{modifier}-z>", bound)


def patch_app_class(module, app_class):
    import unittest.mock

    return unittest.mock.patch.object(module, "resolve_app_class", return_value=app_class)


def patch_gui_app(module_name, main_module):
    import unittest.mock
    from types import ModuleType

    fake_gui_module = ModuleType(module_name)
    fake_gui_module.App = Mock(return_value=Mock(mainloop=Mock()))
    return unittest.mock.patch.object(main_module, "gui_app", fake_gui_module, create=True)


if __name__ == "__main__":
    unittest.main()
