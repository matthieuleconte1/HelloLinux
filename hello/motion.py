"""Mouvement à la façon de SwiftUI (Motion.swift) : des ressorts plutôt que des courbes fixes.

Un ressort se donne comme dans SwiftUI, par son temps de réponse (s) et son amortissement (1 : sans rebond). Il sert
trois fois : en ressort de libadwaita (animations pilotées par l'horloge d'affichage, qui repartent d'où elles en sont
avec leur vitesse), en images clés CSS échantillonnées (GTK interpole alors la vraie courbe du ressort, rendue par le
compositeur de GTK sans rien recalculer), et en durée (le temps qu'il met à se poser).

Deux conteneurs gardent ces animations bon marché :
- `Glide` : la sélection glisse d'une ligne à l'autre (matchedGeometryEffect). Seul le surlignage est replacé à
  chaque image ; la liste n'est pas remise en page.
- `Pinned` : pendant que le panneau change de taille, son contenu garde sa taille finale et n'est que découpé —
  la grille d'applications n'est plus remise en page à chaque image."""
import math

import gi

for _name, _version in (("Gtk", "4.0"), ("Gsk", "4.0"), ("Graphene", "1.0"), ("Adw", "1")):
    try:
        gi.require_version(_name, _version)
    except ValueError:
        pass
from gi.repository import Adw, GLib, Graphene, Gsk, Gtk  # noqa: E402

from .settings import motion_enabled, motion_speed  # noqa: E402


class Spring:
    """Ressort de SwiftUI : `response` (s), `damping` (fraction d'amortissement critique)."""
    __slots__ = ("response", "damping")

    def __init__(self, response, damping=1.0):
        self.response = response
        self.damping = damping

    def __repr__(self):
        return f"Spring({self.response}, {self.damping})"

    def scaled(self, speed=None):
        """Plus rapide ou plus lent selon la vitesse réglée (Réglages › Animations)."""
        speed = motion_speed() if speed is None else speed
        return Spring(self.response / speed, self.damping)

    @property
    def omega(self):
        return 2 * math.pi / self.response

    def value(self, t):
        """Position à l'instant t (s), pour un départ de 0 vers 1, à l'arrêt."""
        if t <= 0:
            return 0.0
        w, z = self.omega, self.damping
        if z < 1:
            wd = w * math.sqrt(1 - z * z)
            return 1 - math.exp(-z * w * t) * (math.cos(wd * t) + z * w / wd * math.sin(wd * t))
        if z == 1:
            return 1 - math.exp(-w * t) * (1 + w * t)
        r1 = -w * (z - math.sqrt(z * z - 1))
        r2 = -w * (z + math.sqrt(z * z - 1))
        return 1 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)

    def settling(self, epsilon=0.001):
        """Temps qu'il met à se poser (écart et vitesse sous `epsilon`), en secondes."""
        step = self.response / 200
        t, last_out = 0.0, 0.0
        while t < self.response * 8:
            t += step
            if abs(1 - self.value(t)) > epsilon:
                last_out = t
        return min(max(last_out + step, step), self.response * 8)

    def adw(self, speed=None):
        """Paramètres d'un Adw.SpringAnimation (masse 1, raideur ω²)."""
        s = self.scaled(speed)
        return Adw.SpringParams.new(s.damping, 1.0, s.omega ** 2)


def snappy(duration):
    """`.snappy(duration:)` de SwiftUI : un ressort vif, à peine rebondi."""
    return Spring(duration, 0.85)


def smooth(duration):
    """`.smooth(duration:)` de SwiftUI : sans rebond."""
    return Spring(duration, 1.0)


def keyframes(name, spring, frame, stops=28, speed=None, at_least=0.0):
    """Images clés CSS d'un ressort : `frame(p, t)` donne les déclarations à la progression p (0 → 1, rebond
    compris) et au temps t (s, déjà mis à la vitesse réglée). Renvoie (bloc @keyframes, durée en ms).
    À jouer en `linear` : la courbe est dans les images. `at_least` : durée minimale (un fondu plus long)."""
    s = spring.scaled(speed)
    duration = max(s.settling(), at_least)
    lines = []
    for i in range(stops + 1):
        x = i / stops
        p = 1.0 if i == stops else s.value(x * duration)
        lines.append(f"{x * 100:.2f}% {{ {frame(p, x * duration)} }}")
    return f"@keyframes {name} {{ {' '.join(lines)} }}", max(1, round(duration * 1000))


def ease_in(x):
    """`.easeIn` de SwiftUI (courbe de Bézier 0,42 0 1 1), approchée."""
    x = min(max(x, 0.0), 1.0)
    return x ** 1.68


def clamp01(v):
    return min(max(v, 0.0), 1.0)


def lerp(a, b, p):
    return a + (b - a) * p


def animate(widget, spring, start, end, apply, done=None, velocity=0.0):
    """Ressort de libadwaita sur une valeur ; `apply(v)` à chaque image. Renvoie l'animation (déjà lancée)."""
    animation = Adw.SpringAnimation.new(widget, start, end, spring.adw(), Adw.CallbackAnimationTarget.new(apply))
    animation.set_clamp(False)
    animation.set_initial_velocity(velocity)
    if done:
        animation.connect("done", lambda *_: done())
    animation.play()
    return animation


def playing(animation):
    return animation is not None and animation.get_state() == Adw.AnimationState.PLAYING


def velocity(animation):
    """Vitesse courante d'un ressort en cours (0 sinon), pour qu'une relance reparte avec son élan."""
    if not playing(animation):
        return 0.0
    try:
        return animation.get_velocity()
    except AttributeError:   # libadwaita < 1.3
        return 0.0


def _translate(x, y):
    point = Graphene.Point()
    point.x, point.y = x, y
    return Gsk.Transform.new().translate(point)


class Glide(Gtk.Widget):
    """Un surlignage qui glisse sous l'élément choisi (ligne de la liste, case de la grille), avec le ressort du
    style (matchedGeometryEffect). Il est dessiné avant le contenu : le texte de la ligne reste au-dessus.

    Une animation CSS de la ligne (arrivée à l'ouverture, changement d'écran) la déplace sans remettre Glide en page :
    après chaque sélection ou mise en page, le surlignage suit donc la ligne image par image, tant qu'elle bouge (il
    arrive avec elle, comme le fond de ligne de la version Mac), puis s'arrête pour ne pas réveiller l'app à vide."""

    FOLLOW_IDLE = 0.8   # s sans mouvement de la ligne avant d'arrêter de la suivre

    def __init__(self, child, css="hello-glide"):
        super().__init__()
        self.child = child
        self.highlight = Gtk.Box()
        for c in css.split():
            self.highlight.add_css_class(c)
        self.highlight.set_can_target(False)
        self.highlight.set_parent(self)
        child.set_parent(self)
        self._target = None          # élément choisi
        self._shown = None           # rectangle affiché (x, y, l, h)
        self._from = self._to = None
        self._progress = 1.0
        self._animation = None
        self.spring = None           # None : saut net
        self._follow = None          # rappel d'image qui suit la ligne
        self._seen = None
        self._still = 0.0
        self.connect("map", lambda *_: self._watch())
        self.connect("unmap", lambda *_: self._unwatch())
        self.set_hexpand(child.get_hexpand())
        self.set_vexpand(child.get_vexpand())

    def _watch(self):
        """Suivre la ligne choisie à chaque image, jusqu'à ce qu'elle ne bouge plus (FOLLOW_IDLE)."""
        self._still = 0.0
        if self._follow is None and self.get_mapped() and self._target is not None:
            self._follow = self.add_tick_callback(self._on_frame)

    def _unwatch(self):
        if self._follow is not None:
            self.remove_tick_callback(self._follow)
            self._follow = None

    def _on_frame(self, _widget, clock):
        now = clock.get_frame_time() / 1e6
        rect = self._bounds(self._target)
        if rect != self._seen:
            self._seen = rect
            self._still = now
            self.queue_allocate()
        elif not self._still:
            self._still = now
        elif now - self._still > self.FOLLOW_IDLE or self._target is None:
            self._follow = None
            return False
        return True

    def do_dispose(self):
        self._unwatch()
        for widget in (self.highlight, self.child):
            if widget.get_parent() is self:
                widget.unparent()

    def do_get_request_mode(self):
        return self.child.get_request_mode()

    def do_measure(self, orientation, for_size):
        minimum, natural, min_base, nat_base = self.child.measure(orientation, for_size)
        return minimum, natural, min_base, nat_base

    def _bounds(self, widget):
        if widget is None or widget.get_parent() is None:
            return None
        # Dans le repère de Glide, celui où le surlignage est placé (celui de l'enfant commence après ses marges et
        # son padding : 8 px de décalage pour la liste).
        ok, rect = widget.compute_bounds(self)
        if not ok or rect.get_width() <= 0:
            return None
        return (rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height())

    def select(self, widget, animate=True):
        """Le surlignage va sous `widget` (None : il disparaît)."""
        same = widget is self._target
        self._target = widget
        # Classes de forme de la cible (premier ou dernier d'un groupe : coins arrondis d'un côté).
        for name in ("first", "last"):
            (self.highlight.add_css_class if widget is not None and widget.has_css_class(name)
             else self.highlight.remove_css_class)(name)
        if same:
            return
        self._watch()
        target = self._bounds(widget)
        if target is None or self._shown is None or not animate or self.spring is None or not motion_enabled():
            self._snap(target)
            return
        self._glide(target)

    def _snap(self, rect):
        if self._animation is not None:
            self._animation.skip() if playing(self._animation) else None
            self._animation = None
        self._from = self._to = rect
        self._progress = 1.0
        self._shown = rect
        self.queue_allocate()

    def _glide(self, target):
        # Relancé en plein vol : repart de là où il est, avec sa vitesse rapportée au nouveau trajet.
        start = self._shown
        speed = 0.0
        if playing(self._animation) and self._from and self._to:
            old = abs(self._to[1] - self._from[1]) + abs(self._to[0] - self._from[0])
            new = abs(target[1] - start[1]) + abs(target[0] - start[0])
            if new > 0:
                speed = velocity(self._animation) * old / new
            self._animation.pause()
        self._from, self._to = start, target
        self._progress = 0.0

        def step(value):
            self._progress = value
            self.queue_allocate()
        self._animation = animate(self, self.spring, 0.0, 1.0, step, velocity=speed)

    def _current(self):
        if self._from is None or self._to is None:
            return self._to
        p = self._progress
        return tuple(lerp(a, b, p) for a, b in zip(self._from, self._to))

    def do_size_allocate(self, width, height, baseline):
        self.child.allocate(width, height, baseline, None)
        # La cible a bougé sans changer (liste refaite, panneau agrandi) : le surlignage la suit sans animation.
        target = self._bounds(self._target)
        if target != self._to:
            if playing(self._animation):
                self._to = target            # le glissement en cours vise la nouvelle position
            else:
                self._from = self._to = target
            self._watch()
        rect = self._current()
        self._shown = rect
        self.highlight.set_child_visible(rect is not None)
        if rect is not None:
            x, y, w, h = rect
            self.highlight.allocate(max(1, round(w)), max(1, round(h)), -1, _translate(round(x), round(y)))


class Pinned(Gtk.Widget):
    """Contenu à taille fixe pendant que son cadre change de taille : il est alloué à `pin` (centré, collé en haut)
    et découpé, au lieu d'être remis en page à chaque image. `pin = None` : il suit son cadre."""

    def __init__(self, child):
        super().__init__()
        self.child = child
        self.pin = None
        child.set_parent(self)
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_hexpand(True)
        self.set_vexpand(True)

    def do_dispose(self):
        if self.child.get_parent() is self:
            self.child.unparent()

    def do_get_request_mode(self):
        return self.child.get_request_mode()

    def do_measure(self, orientation, for_size):
        if self.pin is not None:
            return 0, 0, -1, -1
        return self.child.measure(orientation, for_size)

    def set_pin(self, size):
        if size != self.pin:
            self.pin = size
            self.queue_resize()

    def do_size_allocate(self, width, height, baseline):
        if self.pin is None:
            self.child.allocate(width, height, baseline, None)
            return
        w, h = self.pin
        self.child.allocate(w, h, -1, _translate(round((width - w) / 2), 0))


class Ticker:
    """Un rappel à chaque image (horloge d'affichage du widget), au lieu d'un minuteur à fréquence fixe : les
    animations suivent la fréquence de l'écran (60, 120, 144 Hz…). Sans widget affiché, un minuteur de 16 ms."""

    def __init__(self, callback):
        self.callback = callback
        self.widget = None
        self._tick = None
        self._source = None

    def attach(self, widget):
        self.widget = widget

    def running(self):
        return self._tick is not None or self._source is not None

    def start(self):
        if self.running():
            return
        if self.widget is not None and self.widget.get_mapped():
            self._tick = self.widget.add_tick_callback(self._on_tick)
        else:
            self._source = GLib.timeout_add(16, self._on_timeout)

    def stop(self):
        if self._tick is not None and self.widget is not None:
            self.widget.remove_tick_callback(self._tick)
        if self._source is not None:
            GLib.source_remove(self._source)
        self._tick = self._source = None

    def _on_tick(self, _widget, _clock):
        if self.callback():
            return True
        self._tick = None
        return False

    def _on_timeout(self):
        if self.callback():
            # Le widget vient d'apparaître : on passe sur son horloge.
            if self.widget is not None and self.widget.get_mapped():
                self._source = None
                self._tick = self.widget.add_tick_callback(self._on_tick)
                return False
            return True
        self._source = None
        return False
