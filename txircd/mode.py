# -*- coding: utf-8 -*-


class Modes(object):
    def __init__(self, allowed_modes, perm_checker):
        self.allowed_modes = allowed_modes
        self.perm_checker = perm_checker
        self.modes = set()

    def __str__(self):
        return ''.join(self.modes)

    def combine(self, modes):
        changes = 0
        added = set()
        removed = set()
        bad = set()
        forbidden = set()
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
            elif self.perm_checker(mode):
                changes += 1
                current.add(mode)
            else:
                forbidden.add(mode)
        old = self.modes.copy()
        self.modes.update(added)
        self.modes.difference_update(removed)
        added = self.modes - old
        removed = old - self.modes
        return added, removed, forbidden, bad
