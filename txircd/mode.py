# -*- coding: utf-8 -*-


class Modes(object):
    class UnknownMode(Exception): pass
    class NoPrivileges(Exception): pass

    def __init__(self, allowed_modes):
        self.allowed_modes = allowed_modes
        self.modes = set()

    def __str__(self):
        return ''.join(self.modes)

    def _add(self, mode):
        self.modes.add(mode)

    def _remove(self, mode):
        self.modes.discard(mode)

    def combine(self, modes):
        handler = self._add
        changes = 0
        response = ''
        for mode in modes:
            if changes >= 20:
                break
            elif mode == '+':
                if handler is not self._add:
                    handler = self._add
                    response += '+'
            elif mode == '-':
                if handler is not self._remove:
                    handler = self._remove
                    response += '-'
            elif mode not in self.allowed_modes:
                raise self.UnknownMode(mode)
            else:
                handler(mode)
                changes += 1
                response += mode
        return response
