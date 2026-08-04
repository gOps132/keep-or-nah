import os
import unittest
from unittest.mock import patch
import warnings

import main


class ResolveAppClassTests(unittest.TestCase):
    def test_force_classic_environment_selects_classic_frontend(self):
        with patch.dict(os.environ, {main.FORCE_CLASSIC_ENV_VAR: "1"}, clear=False):
            app_class = main.resolve_app_class()

        self.assertEqual(app_class.__name__, "ClassicApp")
        self.assertEqual(app_class.__module__, "classic_gui")

    def test_normal_environment_selects_primary_frontend(self):
        with warnings.catch_warnings(), patch.dict(os.environ, {}, clear=False), patch.object(
            main.tk, "TkVersion", 8.6
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            os.environ.pop(main.FORCE_CLASSIC_ENV_VAR, None)
            app_class = main.resolve_app_class()

        self.assertEqual(app_class.__name__, "App")
        self.assertEqual(app_class.__module__, "gui_app")


if __name__ == "__main__":
    unittest.main()
