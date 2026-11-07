import sys

import gi

from .launchenv import choose_renderer, clean_process_environment

# Avant tout : les apps lancées ne doivent pas hériter du préchargement de gtk4-layer-shell.
clean_process_environment()
# Moteur GL (animations deux fois moins chères qu'en Vulkan) ; retiré de l'environnement dès la première
# fenêtre réalisée (app.py).
choose_renderer()

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
try:
    gi.require_version("Gtk4LayerShell", "1.0")
except ValueError:
    pass

from .app import main  # noqa: E402

sys.exit(main())
