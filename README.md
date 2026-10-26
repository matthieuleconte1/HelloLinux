# Hello pour Linux

Un lanceur façon Raycast ou Alfred pour Linux : apps, terminal, presse-papiers, emoji, couleurs et un agent IA,
derrière **Alt Espace**. C'est le portage de [Hello pour macOS](https://github.com/matthieuleconte1/Hello) : les six
styles de la version Mac plus un style **KDE** (celui par défaut), en **Python + GTK 4 + libadwaita**. Il est pensé
pour Wayland (KDE Plasma 6 en priorité, mais aussi GNOME, Hyprland et Sway).

C'est un portage, pas une traduction ligne à ligne. SwiftUI, AppKit et Carbon n'existent pas sous Linux, donc
chaque brique système a été remplacée par son équivalent Linux (tableau plus bas). Version : `hello/__init__.py`.

## Installation

```sh
git clone https://github.com/matthieuleconte1/HelloLinux.git && cd HelloLinux
./install.sh            # installe dans ~/.local (lanceur, icône, fichier .desktop) et lance Hello
./install.sh uninstall  # retire Hello (les réglages et l'historique restent)
./install.sh dist       # build/Hello-linux-<version>.tar.gz
./install.sh release    # la même archive, publiée en release GitHub v<version>
```

### Mises à jour

Hello se met à jour tout seul depuis les [releases de ce dépôt](https://github.com/matthieuleconte1/HelloLinux/releases).
Il vérifie au lancement puis toutes les 6 heures. Quand une nouvelle version sort, il attend que le panneau soit
fermé et que l'IA ne travaille pas, télécharge l'archive `Hello-linux-<version>.tar.gz`, vérifie qu'il s'agit bien
de Hello à la bonne version, l'installe dans `~/.local/share/hello/app/<version>` puis se relance en arrière-plan.
Une notification annonce la nouvelle version. Tout se règle dans Réglages › Général : vérification, installation
automatique, préversions.

Pour publier une version : changer `__version__` dans `hello/__init__.py`, puis `./install.sh release`.

### Le raccourci : Alt Espace

Wayland ne permet pas à une app d'écouter le clavier des autres. Hello demande donc son raccourci au bureau,
via le portail **GlobalShortcuts** (Plasma 6, GNOME 48+, Hyprland). **Alt Espace** est proposé par défaut.

Sur Plasma, Hello s'inscrit directement auprès de kglobalaccel, comme une app KDE native (sans portail).
Alt Espace ouvre normalement KRunner : au premier lancement, Hello le reprend, et KRunner garde Alt F2 et la
touche Recherche. Le raccourci ne fonctionne que pendant que Hello tourne (lance-le à l'ouverture de session).
Il apparaît normalement dans
**Configuration du système › Clavier › Raccourcis › Hello**, et on peut le modifier là. Pour rendre
Alt Espace à KRunner, il suffit de l'y réattribuer. Choisir une autre combinaison dans le mode « Raccourci »
du panneau ou dans les réglages la reprend de la même façon.

Sans portail, n'importe quel gestionnaire de raccourcis peut lancer `hello --toggle`.

```sh
hello                 # ouvre le panneau (lance Hello s'il ne tourne pas)
hello --toggle        # ouvre ou ferme
hello --show emoji    # ouvre dans un mode : apps, emoji, clipboard, colors, chats, stats, uninstall…
hello --query "cd ~/" # ouvre avec un texte déjà tapé
hello --settings      # réglages (aussi : Ctrl , dans le panneau)
hello --background    # démarre sans ouvrir (ouverture de session)
hello --quit
```

## Ce qui change par rapport à macOS

| macOS | Linux |
|---|---|
| NSPanel flottant | surface **layer-shell** au-dessus de tout (un clic à côté referme) ; sinon une fenêtre ordinaire |
| Raccourci Carbon ⌘ Espace | **Alt Espace** via le portail **GlobalShortcuts** (repris à KRunner sur Plasma), ou `hello --toggle` |
| Apps de /Applications | fichiers **.desktop** (Gio), y compris Flatpak ; « Ouverte » lu dans les unités systemd des apps |
| NSPasteboard (compteur) | `wl-paste --watch` (protocole data-control) ; les copies marquées secrètes (KeePassXC…) sont ignorées |
| Collage via l'accessibilité | **ydotool** (`systemctl --user enable --now ydotool`) ; sans lui, Hello copie seulement |
| Pipette NSColorSampler | portail **Screenshot.PickColor** (aucune capture gardée) |
| Masquer la barre des menus | **Panneau Plasma** : toujours visible, masquage auto, esquiver les fenêtres, fenêtres par-dessus |
| Désinstallation AppCleaner | Flatpak (`flatpak uninstall`), paquet (`pacman -Rns`, `apt remove`, `dnf remove` dans le terminal), app locale ; restes dans `~/.config`, `~/.local/share`, `~/.cache`, `~/.var/app` → corbeille |
| ⌘ ↵ / ⌥ ↵ / ⌘ ⌫ | **Ctrl ↵** / **Alt ↵** / **⇧ Suppr** |
| Finder | gestionnaire de fichiers par défaut (Dolphin, Nautilus…) via `org.freedesktop.FileManager1` |
| Terminal / éditeur | Ghostty, kitty, WezTerm, Alacritty, foot, Konsole, Terminal GNOME… / Cursor, VS Code, Zed, Kate… |
| Liquid Glass | Verre translucide sur le **flou de KWin** (`backdrop-filter` de GTK, protocole ext-background-effect ; org_kde_kwin_blur sur les KWin plus anciens). Sans flou : verre presque opaque |
| Icône de la barre des menus | icône dans la **zone de notification** (StatusNotifierItem) : clic pour ouvrir, clic droit pour le menu |
| Grille d'apps au trackpad | `Adw.Carousel` : balayage au pavé tactile, molette, Ctrl ← → ou Page ↑ ↓ |
| Capture d'écran pour l'IA (⌘ ⇧ S) | **Ctrl ⇧ S** : portail **Screenshot** interactif (zone, fenêtre ou écran) |
| Joindre un fichier (⌘ O) | **Ctrl O** : sélecteur de fichiers du bureau (portail FileChooser) ; glisser-déposer sur le panneau |
| Coller un fichier ou une image (⌘ V) | **Ctrl V** : fichiers copiés dans Dolphin ou Nautilus, image copiée sans texte (`wl-paste`) |
| Notification de fin de l'IA | `Gio.Notification` : un clic rouvre la conversation |
| Mise à jour (zip de la release) | archive `Hello-linux-<version>.tar.gz` des releases de HelloLinux, installée seule quand le panneau est fermé |

Ces fonctions sont identiques : recherche floue et frécence (mêmes scores), apprentissage des préfixes, `cd` / `z` /
`>` / `kill` / `port` / `:3000` / `ip`, sortie colorée dans un PTY, historique zsh et bash, zoxide, branche git,
commandes perso `{}`, emoji avec recherche en français, couleurs HEX / RGB / HSL, statistiques, mode focus,
les six styles et leurs animations d'ouverture (onde de points et décodage ASCII de l'Atelier Glyphe, Nuit
automatique), et l'agent IA.

## L'agent IA

« ? ta demande » (ou une phrase) interroge l'IA, sur trois niveaux : **Fast** répond tout de suite ou choisit le
niveau, **Recherche & Action** cherche sur le web et agit sur l'ordinateur (shell, D-Bus de KDE ou `gsettings`,
captures d'écran), **Code** ouvre une session de code dans le terminal. « ?? » et « ??? » forcent les niveaux 2
et 3. Chaque niveau a son fournisseur : **Hermes**, **Claude Code** ou **Codex** (Réglages › Agent, avec le
modèle et l'effort de raisonnement).

Sous une réponse, la barre de recherche revient pour une question de suite (↵ niveau 1, Ctrl ↵ niveau 2,
Alt ↵ niveau 3) : l'IA reçoit les échanges précédents. Les conversations sont gardées (mode « Conversations »,
`hello --show chats`, ou « /resume »). Les commandes « / » : `/resume`, `/new`, `/fast`, `/work`, `/code`,
`/retry`, `/terminal`, `/copy`, `/delete`, `/memory`, `/model`, `/help`.

Deux pressions sur **Échap** en moins de 2,5 secondes arrêtent la réponse en cours, ou reviennent à la recherche
si elle est terminée ; une saisie en cours est d'abord effacée. **Ctrl W** masque Hello et laisse l'IA travailler :
une notification prévient quand elle a fini.

## Le style KDE

Le style par défaut suit Plasma. Il reprend le thème de couleurs, la couleur d'accentuation et la police lus
dans `~/.config/kdeglobals`, avec une sélection à la Plasma 6 (accent léger et filet) et le flou de KWin.
Changer de thème dans la Configuration du système met Hello à jour tout de suite, icône de la zone de
notification comprise. Les cinq styles de la version Mac restent disponibles (« style » dans le panneau, ou
Réglages › Apparence).

## La zone de notification

Le logo de Hello apparaît dans la zone de notification, aux couleurs du thème. Un clic ouvre ou ferme le
panneau. Le clic droit ouvre le menu de la version Mac : Emoji, Presse-papiers, Pipette, visibilité du
panneau Plasma, Statistiques, Réglages, lancement à l'ouverture de session et Quitter. L'option se trouve
dans Réglages › Général.

## Données

- Réglages : `~/.config/hello/settings.json`
- Statistiques, presse-papiers (0600), couleurs, historique : `~/.local/share/hello/`
- Conversations avec l'IA (0600) : `~/.local/share/hello/chats.json` (Réglages › Agent › Mémoire pour les effacer)
- Versions installées par la mise à jour : `~/.local/share/hello/app/`

## Sous le capot

| Fichier | Rôle |
|---|---|
| `hello/app.py` | l'application (une seule instance via D-Bus), ouverture et fermeture, démarrage |
| `hello/model.py` | les modes, la recherche, le clavier, les actions (LauncherModel) |
| `hello/ui.py` | le panneau GTK : liste, grille d'apps, emoji, aperçus, terminal, agent |
| `hello/styles.py`, `hello/mark.py`, `hello/decode.py` | les sept styles (CSS GTK générée, style KDE lu dans kdeglobals), leurs ouvertures (mouvement du panneau, cascade des lignes, signature dessinée), le logo et le décodage ASCII |
| `hello/blur.py`, `hello/tray.py` | détection du flou du compositeur, icône et menu de la zone de notification |
| `hello/prefs.py` | les réglages (libadwaita) |
| `hello/apps.py`, `hello/usage.py`, `hello/fuzzy.py` | index des apps, frécence, recherche floue |
| `hello/shell.py`, `hello/term.py` | commandes, PTY, séquences ANSI, dossiers, processus, ports |
| `hello/clipboard.py`, `hello/glyphs.py`, `hello/colors.py` | presse-papiers, emoji, pipette et panneau Plasma |
| `hello/uninstall.py` | désinstallation |
| `hello/agent.py`, `hello/engines.py` | l'agent et ses trois niveaux ; Hermes, Claude Code et Codex (arguments, flux JSON) |
| `hello/chats.py`, `hello/context.py`, `hello/confirm.py` | conversations, pièces jointes et contexte, Échap en deux temps |
| `hello/updater.py` | mises à jour depuis les releases GitHub |
| `data/icons/` | les icônes de Hello, tirées de [Phosphor](https://phosphoricons.com) (licence MIT, `LICENSE-phosphor`) ; le menu de la zone de notification garde celles du thème, puisque c'est Plasma qui le dessine |
| `hello/hotkey.py`, `hello/portal.py`, `hello/desktop.py` | portails XDG, intégration au bureau |

Tests : `python3 -m unittest discover -s tests`
