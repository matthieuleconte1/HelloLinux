import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
except ValueError:
    pass

from .app import main  # noqa: E402

sys.exit(main())
