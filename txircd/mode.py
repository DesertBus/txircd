# -*- coding: utf-8 -*-


class Modes(object):
    class NoPrivileges(Exception): pass

    def __init__(self, allowed_modes):
        self.allowed_modes = allowed_modes
        self.modes = set()

    def __str__(self):
        return ''.join(self.modes)

    def combine(self, modes):
        changes = 0
        added = set()
        removed = set()
        bad = set()
        current = added
        for mode in modes:
            if changes >= 20:
                break
            elif mode == '+':
                current = added
            elif mode == '-':
                current = removed
            elif mode not in self.allowed_modes:
                bad.add(mode)
            else:
                changes += 1
                current.add(mode)
        self.modes.update(added)
        self.modes.difference_update(removed)
        return added, removed, bad
