"""Environnement transmis aux programmes que Hello lance.

bin/hello précharge gtk4-layer-shell (LD_PRELOAD) et ajoute son dossier au PYTHONPATH : ces deux variables ne
servent qu'à Hello. Laissées dans l'environnement, elles passent à chaque app ouverte : une app GTK 3 ou Electron
(Cider…) qui reçoit gtk4-layer-shell plante dès son lancement (« gdk_display_manager_get() was called before
gtk_init() »), alors qu'elle s'ouvre bien depuis le menu de Plasma. Elles s'empilaient aussi à chaque mise à jour,
install.sh relançant Hello avec l'environnement hérité.

Une fois Python démarré, la bibliothèque est chargée et sys.path est fixé : on peut les retirer sans effet sur Hello.

Moteur de rendu de GSK : Hello dessine avec le moteur GL plutôt que Vulkan (le défaut de GTK sous Wayland). Sur la
même ouverture de panneau, Vulkan coûtait 8 à 14 ms par image contre 4 à 7 ms en GL (RTX 4070, écran à 240 Hz,
scripts/bench-motion.py --replay) : l'animation ne suivait plus l'écran. GTK lit GSK_RENDERER une seule fois, au
premier moteur créé (réalisation de la première fenêtre) : Hello la pose au démarrage et la retire juste après, pour
que les apps lancées gardent leur propre moteur. Un GSK_RENDERER posé par l'utilisateur est respecté.
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


RENDERER = "gl"
_own_renderer = False


def choose_renderer(env=os.environ):
    """Le moteur GL pour Hello, sauf si l'utilisateur en a choisi un. Renvoie True si Hello l'a posé."""
    global _own_renderer
    if env.get("GSK_RENDERER"):
        return False
    env["GSK_RENDERER"] = RENDERER
    if env is os.environ:
        _own_renderer = True
    return True


def release_renderer(*_):
    """Retire la variable posée par Hello, une fois le moteur de sa première fenêtre créé (à sa réalisation) :
    GTK a retenu son choix, les apps lancées ensuite n'en héritent pas."""
    global _own_renderer
    if _own_renderer:
        os.environ.pop("GSK_RENDERER", None)
        _own_renderer = False


def clean_process_environment():
    """Applique `cleaned` à l'environnement du processus (os.environ appelle putenv/unsetenv : Gio, qui lit
    l'environnement C au lancement d'une app, en profite aussi). À appeler avant tout fil d'exécution."""
    target = cleaned(os.environ)
    for key in ("LD_PRELOAD", "PYTHONPATH"):
        if key in target:
            os.environ[key] = target[key]
        else:
            os.environ.pop(key, None)
