import sys

import gi

from .launchenv import clean_process_environment

# Avant tout : les apps lancées ne doivent pas hériter du préchargement de gtk4-layer-shell.
clean_process_environment()

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
except ValueError:
    pass

from .app import main  # noqa: E402

sys.exit(main())
