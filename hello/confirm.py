"""Deux pressions distinctes, pour la même action, dans une fenêtre courte (EscapeConfirmation.swift) :
Échap deux fois pour arrêter l'IA ou quitter sa réponse."""
import time

WINDOW = 2.5


class EscapeConfirmation:
    def __init__(self):
        self._action = None
        self._deadline = 0.0

    def press(self, action, now=None):
        """action : « cancel » ou « leave ». True à la seconde pression dans la fenêtre."""
        now = time.monotonic() if now is None else now
        if self._action == action and now < self._deadline:
            self.reset()
            return True
        self._action = action
        self._deadline = now + WINDOW
        return False

    def reset(self):
        self._action = None
        self._deadline = 0.0
