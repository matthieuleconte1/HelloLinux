"""Environnement transmis aux programmes que Hello lance.

bin/hello précharge gtk4-layer-shell (LD_PRELOAD) et ajoute son dossier au PYTHONPATH : ces deux variables ne
servent qu'à Hello. Laissées dans l'environnement, elles passent à chaque app ouverte : une app GTK 3 ou Electron
(Cider…) qui reçoit gtk4-layer-shell plante dès son lancement (« gdk_display_manager_get() was called before
gtk_init() »), alors qu'elle s'ouvre bien depuis le menu de Plasma. Elles s'empilaient aussi à chaque mise à jour,
install.sh relançant Hello avec l'environnement hérité.

Une fois Python démarré, la bibliothèque est chargée et sys.path est fixé : on peut les retirer sans effet sur Hello.
"""
import os
import re

_LAYER_SHELL = re.compile(r"(^|/)libgtk4-layer-shell\.so(\.\d+)*$")


def _is_hello_root(path):
    return (os.path.isfile(os.path.join(path, "hello", "__init__.py"))
            and os.path.isfile(os.path.join(path, "bin", "hello")))


def cleaned(env):
    """Copie de `env` sans les ajouts de bin/hello ; les valeurs propres à l'utilisateur sont gardées."""
    env = dict(env)
    preload = [p for p in re.split(r"[: ]+", env.get("LD_PRELOAD", "")) if p and not _LAYER_SHELL.search(p)]
    if preload:
        env["LD_PRELOAD"] = ":".join(preload)
    else:
        env.pop("LD_PRELOAD", None)
    paths = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and not _is_hello_root(p)]
    if paths:
        env["PYTHONPATH"] = os.pathsep.join(paths)
    else:
        env.pop("PYTHONPATH", None)
    return env


def clean_process_environment():
    """Applique `cleaned` à l'environnement du processus (os.environ appelle putenv/unsetenv : Gio, qui lit
    l'environnement C au lancement d'une app, en profite aussi). À appeler avant tout fil d'exécution."""
    target = cleaned(os.environ)
    for key in ("LD_PRELOAD", "PYTHONPATH"):
        if key in target:
            os.environ[key] = target[key]
        else:
            os.environ.pop(key, None)
