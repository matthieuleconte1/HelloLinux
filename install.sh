#!/usr/bin/env bash
# ./install.sh            → installe Hello pour l'utilisateur (~/.local) et le lance
# ./install.sh dist       → build/Hello-linux-<version>.tar.gz (ce que la mise à jour intégrée télécharge)
# ./install.sh release    → comme dist, puis publie la release GitHub v<version> (version : hello/__init__.py)
# ./install.sh --update   → utilisé par la mise à jour intégrée : installe et relance Hello en arrière-plan
# ./install.sh uninstall  → retire Hello (les réglages et l'historique restent dans ~/.config/hello et ~/.local/share/hello)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

APP_ID=io.github.matthieuleconte1.Hello
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP_ID.desktop"

if [[ "${1:-}" == "dist" || "${1:-}" == "release" ]]; then
    # Archive de la release GitHub : c'est ce que la mise à jour intégrée télécharge (hello/updater.py).
    VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' hello/__init__.py)
    NAME="Hello-linux-$VERSION"
    STAGE=$(mktemp -d)
    mkdir "$STAGE/$NAME"
    cp -R install.sh bin hello data README.md LICENSE "$STAGE/$NAME/" 2>/dev/null || \
        cp -R install.sh bin hello data README.md "$STAGE/$NAME/"
    find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
    mkdir -p build
    tar -czf "build/$NAME.tar.gz" -C "$STAGE" "$NAME"
    rm -rf "$STAGE"
    echo "✓ build/$NAME.tar.gz"
    if [[ "${1:-}" == "release" ]]; then
        # Une version avec suffixe (2.1.0-beta.1) part en préversion.
        PRE=()
        [[ "$VERSION" == *-* ]] && PRE=(--prerelease)
        gh release create "v$VERSION" "build/$NAME.tar.gz" --title "Hello pour Linux $VERSION" --generate-notes "${PRE[@]}"
        echo "✓ release v$VERSION publiée : les Hello installés l'installeront d'eux-mêmes"
    fi
    exit 0
fi

if [[ "${1:-}" == "uninstall" ]]; then
    "$BIN_DIR/hello" --quit 2>/dev/null || true
    rm -f "$BIN_DIR/hello" "$APPS_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.svg" "$AUTOSTART"
    echo "✓ Hello retiré"
    exit 0
fi

# Dépendances : Python GObject, GTK 4, libadwaita ; gtk4-layer-shell et wl-clipboard fortement conseillés.
missing=()
python3 - <<'PY' || missing+=(gtk)
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
PY
python3 -c 'import gi; gi.require_version("Gtk4LayerShell", "1.0")' 2>/dev/null || missing+=(layer-shell)
command -v wl-paste >/dev/null || missing+=(wl-clipboard)
if (( ${#missing[@]} )); then
    echo "Il manque : ${missing[*]}"
    if command -v pacman >/dev/null; then
        echo "  sudo pacman -S --needed python-gobject gtk4 libadwaita gtk4-layer-shell wl-clipboard"
    elif command -v apt >/dev/null; then
        echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtk4layershell-1.0 wl-clipboard"
    elif command -v dnf >/dev/null; then
        echo "  sudo dnf install python3-gobject gtk4 libadwaita gtk4-layer-shell wl-clipboard"
    fi
    [[ " ${missing[*]} " == *" gtk "* ]] && exit 1
    echo "(Hello marche sans, avec moins de fonctions.)"
fi

mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
ln -sf "$PWD/bin/hello" "$BIN_DIR/hello"
sed "s|@EXEC@|$BIN_DIR/hello|" "data/$APP_ID.desktop" > "$APPS_DIR/$APP_ID.desktop"
PYTHONPATH="$PWD" python3 -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); from hello.mark import write_icon_svg; write_icon_svg('$ICON_DIR/$APP_ID.svg')"
# Lancement à l'ouverture de session déjà activé : il suit le lanceur installé (une ancienne copie a pu bouger).
[[ -f "$AUTOSTART" ]] && sed -i "s|^Exec=.*|Exec=$BIN_DIR/hello --background|" "$AUTOSTART"
update-desktop-database "$APPS_DIR" 2>/dev/null || true
gtk-update-icon-cache -q "${ICON_DIR%/scalable/apps}" 2>/dev/null || true
echo "✓ installé : $BIN_DIR/hello"

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "  (ajoute $BIN_DIR à ton PATH pour taper « hello »)";; esac

if ! command -v ydotool >/dev/null; then
    echo "  Collage direct (↵ colle dans l'app active) : installe ydotool, puis « systemctl --user enable --now ydotool »"
fi

"$BIN_DIR/hello" --quit 2>/dev/null || true
sleep 0.3
if [[ "${1:-}" == "--update" ]]; then
    # Mise à jour intégrée : Hello revient sans ouvrir le panneau, et prévient qu'il est à jour.
    setsid "$BIN_DIR/hello" --background >/dev/null 2>&1 < /dev/null &
    exit 0
fi
setsid "$BIN_DIR/hello" >/dev/null 2>&1 < /dev/null &
echo "✓ lancé — la première fois, le bureau demande de confirmer le raccourci (Alt Espace : sur Plasma, il est repris à KRunner, qui garde Alt F2)"
