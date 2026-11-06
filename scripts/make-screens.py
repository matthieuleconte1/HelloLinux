#!/usr/bin/env python3
"""Captures du README : python3 scripts/make-screens.py → docs/hero.png, docs/screens/*.png, docs/styles/*.png

La vraie fenêtre de Hello, rendue par GTK : Hello est lancé dans un KWin virtuel (Wayland, échelle 2, rien ne
s'affiche à l'écran), sur un bus D-Bus à part, avec des réglages et des données jetables — seul le fichier de
statistiques (~/.local/share/hello/usage.json) est copié, pour que les récents soient de vraies apps. Le presse-papiers,
les conversations et les réglages de l'utilisateur ne sont jamais lus. Une conversation d'exemple montre l'IA.

Le panneau est capturé tel que GTK le dessine (sans le flou de KWin derrière lui), sur fond noir, comme les captures
de la version Mac. Demande kwin_wayland, PyGObject et gtk4-layer-shell."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
MARGIN = 30          # fond noir autour du panneau, en points
SCALE = 2

ANSWER = r"""**Compare trois lois de probabilité**

La **loi normale** $\mathcal{N}(\mu, \sigma^2)$ a pour densité

$$
f(x) = \frac{1}{\sigma\sqrt{2\pi}} e^{-\frac{(x-\mu)^2}{2\sigma^2}}
$$

| Loi | Espérance | Variance |
|---|:-:|:-:|
| Bernoulli $\mathcal{B}(p)$ | $p$ | $p(1-p)$ |
| Poisson $\mathcal{P}(\lambda)$ | $\lambda$ | $\lambda$ |
| Normale $\mathcal{N}(\mu, \sigma^2)$ | $\mu$ | $\sigma^2$ |

- Pour $n$ grand, $\mathcal{B}(n, p) \approx \mathcal{N}(np,\ np(1-p))$.
- Somme des probabilités : $\sum_{k=0}^{\infty} \frac{\lambda^k}{k!} e^{-\lambda} = 1$
"""

BASE = {"onboarded": True, "showTrayIcon": False, "autoUpdateCheck": False, "autoUpdateInstall": False,
        "animations": False, "agentEnabled": True}

# (fichier, réglages, mode)
SHOTS = [
    ("hero.png", {"panelStyle": "kde"}, "root"),
    ("screens/night.png", {"panelStyle": "glyph", "glyphAppearance": "night"}, "root"),
    ("screens/night-apps.png", {"panelStyle": "glyph", "glyphAppearance": "night"}, "apps"),
    # Grand panneau : la réponse tient sans défiler.
    ("screens/ai.png", {"panelStyle": "glyph", "glyphAppearance": "dark", "panelSize": "large"}, "chat"),
    ("styles/kde.png", {"panelStyle": "kde"}, "root"),
    ("styles/glass.png", {"panelStyle": "glass"}, "root"),
    ("styles/atelier.png", {"panelStyle": "atelier", "atelierAppearance": "dark"}, "root"),
    ("styles/glyph.png", {"panelStyle": "glyph", "glyphAppearance": "light"}, "root"),
    ("styles/glyph-dark.png", {"panelStyle": "glyph", "glyphAppearance": "dark"}, "root"),
    ("styles/phosphor.png", {"panelStyle": "phosphor"}, "root"),
    ("styles/paper.png", {"panelStyle": "paper"}, "root"),
    ("styles/brutal.png", {"panelStyle": "brutal"}, "root"),
]


def layer_shell():
    for lib in ("/usr/lib/libgtk4-layer-shell.so", "/usr/lib64/libgtk4-layer-shell.so",
                "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so.0", "/usr/lib/libgtk4-layer-shell.so.0"):
        if os.path.exists(lib):
            return lib
    return None


def prepare():
    """Dossier jetable, puis Hello dans un KWin virtuel ; ce script y repart en mode capture."""
    tmp = tempfile.mkdtemp(prefix="hello-screens-")
    config, data = os.path.join(tmp, "config", "hello"), os.path.join(tmp, "data", "hello")
    os.makedirs(config)
    os.makedirs(data)
    with open(os.path.join(config, "settings.json"), "w") as f:
        json.dump(BASE, f)
    # Récents : seulement les apps (ni commandes ni dossiers) des statistiques de l'utilisateur.
    usage = os.path.join(os.path.expanduser("~"), ".local", "share", "hello", "usage.json")
    try:
        with open(usage) as f:
            records = {k: v for k, v in json.load(f).items() if k.startswith("app:")}
    except (OSError, ValueError, AttributeError):
        records = {}
    with open(os.path.join(data, "usage.json"), "w") as f:
        json.dump(records, f)
    turn = {"id": str(uuid.uuid4()), "date": time.time(), "level": 1, "request": "compare trois lois de probabilité",
            "answer": ANSWER, "kind": "answer", "steps": [], "attachments": [], "sessionID": None, "engine": "hermes"}
    with open(os.path.join(data, "chats.json"), "w") as f:
        json.dump([{"id": str(uuid.uuid4()), "turns": [turn]}], f)
    env = {"HELLO_SCREENS": "1", "XDG_CONFIG_HOME": os.path.join(tmp, "config"),
           "XDG_DATA_HOME": os.path.join(tmp, "data"), "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
           "PYTHONPATH": ROOT, "GDK_BACKEND": "wayland"}
    preload = layer_shell()
    if preload:
        env["LD_PRELOAD"] = preload
    runner = os.path.join(tmp, "run.sh")
    with open(runner, "w") as f:
        f.write("#!/bin/sh\n" + " ".join(f"{k}='{v}'" for k, v in env.items())
                + f" exec /usr/bin/python3 '{os.path.abspath(__file__)}' > '{tmp}/log.txt' 2>&1\n")
    os.chmod(runner, 0o755)
    try:
        subprocess.run(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--no-lockscreen",
                        "--socket", f"hello-screens-{os.getpid()}", "--width", "2800", "--height", "1800",
                        "--scale", str(SCALE), "--exit-with-session", runner],
                       timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        with open(os.path.join(tmp, "log.txt")) as f:
            print("".join(line for line in f if line.startswith(("✓", "✗"))), end="")
        shutil.rmtree(tmp, ignore_errors=True)


def capture():
    """Dans le KWin virtuel : Hello tourne dans ce processus ; chaque capture applique ses réglages, ouvre le
    panneau, attend qu'il soit dessiné (icônes au trait comprises) et l'enregistre."""
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gsk", "4.0")
    gi.require_version("Graphene", "1.0")
    gi.require_version("Adw", "1")
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
    except ValueError:
        pass
    from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk
    from hello import portal
    from hello.app import HelloApp
    from hello.chats import ChatStore
    from hello.settings import DEFAULTS, settings

    portal.register_app()
    GLib.set_application_name("Hello")
    app = HelloApp()
    queue = list(SHOTS)

    def save(name):
        # Toute la fenêtre (le panneau seul s'arrête à ses bords : son ombre pleine serait coupée), recadrée sur
        # le panneau et sa marge.
        w = app.window
        root = w.get_child()
        ok, rect = w.panel_holder.compute_bounds(root)
        x, y, width, height = rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height()
        snapshot = Gtk.Snapshot()
        snapshot.scale(SCALE, SCALE)
        snapshot.append_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=1),
                              Graphene.Rect().init(0, 0, root.get_width(), root.get_height()))
        Gtk.WidgetPaintable.new(root).snapshot(snapshot, root.get_width(), root.get_height())
        node = snapshot.to_node()
        renderer = Gsk.CairoRenderer()
        renderer.realize_for_display(Gdk.Display.get_default())
        bounds = Graphene.Rect().init((x - MARGIN) * SCALE, (y - MARGIN) * SCALE, (width + 2 * MARGIN) * SCALE,
                                      (height + 2 * MARGIN) * SCALE)
        texture = renderer.render_texture(node, bounds)
        renderer.unrealize()
        path = os.path.join(DOCS, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        texture.save_to_png(path)
        print(f"✓ docs/{name} ({texture.get_width()}×{texture.get_height()})", flush=True)

    def step():
        if not queue:
            app.quit()
            return False
        name, values, mode = queue.pop(0)
        app.hide()
        for key in ("panelStyle", "glyphAppearance", "atelierAppearance", "panelSize"):
            setattr(settings, key, values.get(key, DEFAULTS[key]))
        if mode == "chat":
            app.show("root")
            ChatStore.load()
            app.model.open_conversation(ChatStore.conversations[0])
        else:
            app.show(mode)
        # Le temps du rendu, du chargement des icônes et de leur dessin au trait (calculé à part).
        GLib.timeout_add(2500 if values.get("glyphAppearance") == "night" else 1200, lambda: shoot(name))
        return False

    def shoot(name):
        try:
            save(name)
        except Exception as error:   # une capture ratée n'empêche pas les suivantes
            print(f"✗ docs/{name} : {error}", flush=True)
        GLib.timeout_add(200, step)
        return False

    def started(*_):
        GLib.timeout_add(1500, step)
    app.connect("startup", started)
    GLib.timeout_add_seconds(200, lambda: (print("✗ délai dépassé", flush=True), app.quit()))
    app.run(["hello", "--background"])


if __name__ == "__main__":
    if os.environ.get("HELLO_SCREENS"):
        capture()
    else:
        prepare()
