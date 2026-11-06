#!/usr/bin/env python3
"""Banc des animations : python3 scripts/bench-motion.py [--film DOSSIER] [style…]

Hello tourne dans un KWin virtuel (rien ne s'affiche à l'écran), avec des réglages jetables. Des scénarios sont
joués comme au clavier (ouverture, frappe, sélection, grille d'apps, page suivante, retour) et l'horloge d'affichage
de GTK relève chaque image : son intervalle, et le temps passé sur le fil principal (mise à jour + mise en page)
avant le dessin. Une image qui dépasse 1,5 intervalle est une saccade.

Le rendu GPU du KWin virtuel est logiciel : seule la part « fil principal » se compare à une vraie machine.

--film DOSSIER : en plus, le panneau est capturé à plusieurs instants de chaque scénario (FILM_MS), en planches PNG
(une par scénario), pour vérifier à l'œil les images intermédiaires."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


FILM_MS = (0, 30, 60, 100, 150, 220, 320, 600)


def prepare(styles, film=None):
    tmp = tempfile.mkdtemp(prefix="hello-bench-")
    config, data = os.path.join(tmp, "config", "hello"), os.path.join(tmp, "data", "hello")
    os.makedirs(config)
    os.makedirs(data)
    with open(os.path.join(config, "settings.json"), "w") as f:
        json.dump({"onboarded": True, "showTrayIcon": False, "autoUpdateCheck": False, "autoUpdateInstall": False}, f)
    usage = os.path.join(os.path.expanduser("~"), ".local", "share", "hello", "usage.json")
    try:
        with open(usage) as f:
            records = {k: v for k, v in json.load(f).items() if k.startswith("app:")}
    except (OSError, ValueError, AttributeError):
        records = {}
    with open(os.path.join(data, "usage.json"), "w") as f:
        json.dump(records, f)
    env = {"HELLO_BENCH": ",".join(styles), "XDG_CONFIG_HOME": os.path.join(tmp, "config"),
           "XDG_DATA_HOME": os.path.join(tmp, "data"), "XDG_CACHE_HOME": os.path.join(tmp, "cache"),
           "PYTHONPATH": ROOT, "GDK_BACKEND": "wayland", "HELLO_BENCH_OUT": os.path.join(tmp, "out.json"),
           "HELLO_BENCH_FILM": os.path.abspath(film) if film else ""}
    for lib in ("/usr/lib/libgtk4-layer-shell.so", "/usr/lib/x86_64-linux-gnu/libgtk4-layer-shell.so.0"):
        if os.path.exists(lib):
            env["LD_PRELOAD"] = lib
            break
    runner = os.path.join(tmp, "run.sh")
    with open(runner, "w") as f:
        f.write("#!/bin/sh\n" + " ".join(f"{k}='{v}'" for k, v in env.items())
                + f" exec /usr/bin/python3 '{os.path.abspath(__file__)}' > '{tmp}/log.txt' 2>&1\n")
    os.chmod(runner, 0o755)
    try:
        subprocess.run(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--no-lockscreen",
                        "--socket", f"hello-bench-{os.getpid()}", "--width", "2400", "--height", "1500",
                        "--exit-with-session", runner],
                       timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(os.path.join(tmp, "log.txt")) as f:
            log = f.read()
        if "Traceback" in log or "CRITICAL" in log:
            print("Erreurs de l'app :\n" + log[-4000:])
        with open(os.path.join(tmp, "out.json")) as f:
            report(json.load(f))
    except FileNotFoundError:
        with open(os.path.join(tmp, "log.txt")) as f:
            print(f.read()[-3000:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def report(results):
    """action : temps passé dans la réaction à la touche (le fil principal est bloqué pendant ce temps) ;
    blocage : plus long arrêt du fil principal ; images : nombre d'images dessinées dans la fenêtre du scénario."""
    print(f"{'scénario':32} {'images':>6} {'action max':>10} {'blocage':>8} {'mise en page':>12} {'dessin':>8}")
    for name, frames, actions, stall in results:
        work = max((f[1] for f in frames), default=0)
        paint = max((f[2] for f in frames), default=0)
        print(f"{name:32} {len(frames):6} {max(actions, default=0):8.1f}ms {stall:6.1f}ms {work:10.1f}ms "
              f"{paint:6.1f}ms")


def bench():
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    try:
        gi.require_version("Gtk4LayerShell", "1.0")
    except ValueError:
        pass
    from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk
    from hello import portal
    from hello.app import HelloApp
    from hello.settings import settings

    portal.register_app()
    GLib.set_application_name("Hello")
    app = HelloApp()
    styles = os.environ["HELLO_BENCH"].split(",")
    results = []
    recording = {"name": None, "frames": [], "start": 0.0, "actions": [], "stall": 0.0, "tick": 0.0}

    def watchdog():
        """Toutes les 4 ms, en priorité haute : un retard, c'est le fil principal bloqué."""
        now = time.perf_counter()
        if recording["name"] is not None and recording["tick"]:
            recording["stall"] = max(recording["stall"], (now - recording["tick"]) * 1000 - 4)
        recording["tick"] = now
        return True
    GLib.timeout_add(4, watchdog, priority=GLib.PRIORITY_HIGH)

    film = os.environ.get("HELLO_BENCH_FILM")
    frames_dir = os.path.join(film, "frames") if film else None

    def grab(path):
        w = app.window
        root = w.get_child()
        ok, rect = w.panel_holder.compute_bounds(root)
        if not ok:
            return
        snapshot = Gtk.Snapshot()
        snapshot.append_color(Gdk.RGBA(red=0.12, green=0.12, blue=0.14, alpha=1),
                              Graphene.Rect().init(0, 0, root.get_width(), root.get_height()))
        Gtk.WidgetPaintable.new(root).snapshot(snapshot, root.get_width(), root.get_height())
        renderer = Gsk.CairoRenderer()
        renderer.realize_for_display(Gdk.Display.get_default())
        bounds = Graphene.Rect().init(rect.get_x() - 30, max(0, rect.get_y() - 60), rect.get_width() + 60,
                                      min(root.get_height(), 760))
        renderer.render_texture(snapshot.to_node(), bounds).save_to_png(path)
        renderer.unrealize()

    def key(keyval):
        app.model.key(keyval, Gdk.ModifierType(0), False)

    def scenario(name, actions, length):
        """actions : [(délai en ms, fonction)] ; on enregistre `length` ms d'images."""
        def timed(action):
            start = time.perf_counter()
            action()
            recording["actions"].append((time.perf_counter() - start) * 1000)
            return False

        def go():
            recording.update(name=name, frames=[], actions=[], stall=0.0, tick=time.perf_counter())
            for delay, action in actions:
                GLib.timeout_add(delay, lambda a=action: timed(a))
            if frames_dir:
                os.makedirs(frames_dir, exist_ok=True)
                slug = "".join(c if c.isalnum() else "-" for c in name)
                for index, at in enumerate(FILM_MS):
                    GLib.timeout_add(at + 1, lambda i=index, a=at: (grab(os.path.join(
                        frames_dir, f"{slug}~{i}~{a}.png")), False)[1])
            GLib.timeout_add(length, stop)
            return False

        def stop():
            results.append((name, recording["frames"], recording["actions"], recording["stall"]))
            recording["name"] = None
            GLib.timeout_add(250, step)
            return False
        return go

    plan = []
    for style in styles:
        def setup(style=style):
            app.hide()
            settings.panelStyle = style
            if style == "glyph":
                settings.glyphAppearance = "dark"
        plan += [
            (setup, 400),
            (scenario(f"{style} · ouverture", [(0, lambda: app.show("root"))], 900), 0),
            (scenario(f"{style} · frappe « fir »", [(0, lambda: app.model.set_query("f")),
                                                     (110, lambda: app.model.set_query("fi")),
                                                     (220, lambda: app.model.set_query("fir")),
                                                     (330, lambda: app.model.set_query(""))], 800), 0),
            (scenario(f"{style} · sélection ↓ ×6", [(i * 140, lambda: key(Gdk.KEY_Down)) for i in range(6)], 1100), 0),
            (scenario(f"{style} · vers la grille", [(0, lambda: app.model.enter("apps"))], 900), 0),
            (scenario(f"{style} · page suivante", [(0, lambda: key(Gdk.KEY_Page_Down))], 700), 0),
            (scenario(f"{style} · retour", [(0, lambda: app.model.back())], 800), 0),
            (scenario(f"{style} · effacement", [(0, lambda: app.hide(tint=True))], 500), 0),
        ]

    def step():
        if not plan:
            with open(os.environ["HELLO_BENCH_OUT"], "w") as f:
                json.dump(results, f)
            app.quit()
            return False
        action, wait = plan.pop(0)
        action()
        GLib.timeout_add(max(wait, 1), lambda: (step(), False)[1]) if wait else None
        return False

    def hook():
        clock = app.window.get_frame_clock()
        if clock is None:
            return True

        def before(c):
            recording["start"] = time.perf_counter()

        def after_layout(c):
            recording["laid"] = time.perf_counter()

        def after_paint(c):
            if recording["name"] is not None:
                now = time.perf_counter()
                recording["frames"].append((c.get_frame_time() / 1000,
                                            (recording.get("laid", now) - recording["start"]) * 1000,
                                            (now - recording.get("laid", now)) * 1000))
        clock.connect("before-paint", before)
        clock.connect_after("layout", after_layout)
        clock.connect_after("after-paint", after_paint)
        return False

    def started(*_):
        app.show("root")
        GLib.timeout_add(300, hook)
        GLib.timeout_add(1500, step)
    app.connect("startup", started)
    GLib.timeout_add_seconds(500, lambda: (print("délai dépassé"), app.quit()))
    app.run(["hello", "--background"])


def sheets(film):
    """Une planche par scénario : ses captures côte à côte, l'instant sous chacune."""
    import cairo
    frames = os.path.join(film, "frames")
    groups = {}
    for name in sorted(os.listdir(frames)):
        slug, index, at = name[:-4].split("~")
        groups.setdefault(slug, []).append((int(index), int(at), os.path.join(frames, name)))
    for slug, shots in groups.items():
        images = [(at, cairo.ImageSurface.create_from_png(path)) for _, at, path in sorted(shots)]
        width = sum(i.get_width() for _, i in images) + 8 * (len(images) + 1)
        height = max(i.get_height() for _, i in images) + 40
        sheet = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        ctx = cairo.Context(sheet)
        ctx.set_source_rgb(0.05, 0.05, 0.06)
        ctx.paint()
        x = 8
        for at, image in images:
            ctx.set_source_surface(image, x, 8)
            ctx.paint()
            ctx.set_source_rgb(1, 1, 1)
            ctx.set_font_size(18)
            ctx.move_to(x + 6, height - 10)
            ctx.show_text(f"{at} ms")
            x += image.get_width() + 8
        sheet.write_to_png(os.path.join(film, f"{slug}.png"))
    shutil.rmtree(frames, ignore_errors=True)
    print(f"planches : {film}")


if __name__ == "__main__":
    if os.environ.get("HELLO_BENCH"):
        bench()
    else:
        args = sys.argv[1:]
        film = None
        if args[:1] == ["--film"]:
            film, args = args[1], args[2:]
        prepare(args or ["kde", "glyph"], film)
        if film and os.path.isdir(os.path.join(film, "frames")):
            sheets(film)
