# -*- coding: utf-8 -*-


class Modes(object):
    allowed_modes = ""
    param_modes = ""
    def __init__(self, allowed_modes = None, param_modes = None, default_modes = None, user = None, perm_checker = None):
        self.modes = set()
        self.params = {}
        if allowed_modes is not None:
            self.allowed_modes = allowed_modes
        if param_modes is not None:
            self.param_modes = param_modes
        if perm_checker is not None:
            self.perm_checker = perm_checker
        if default_modes is not None:
            params = default_modes.split(" ")
            self.combine(params[0], params[1:], user)

    def __str__(self):
        return ''.join(self.modes)

    def perm_checker(self, perm):
        return True
    
    def has(self, perm):
        return perm in self.modes
    
    def get(self, perm):
        return self.params[perm]
    
    def add_param(self, mode, param, user):
        method = getattr(self, "add_param_%s" % mode, None)
        if method is not None:
            method(param, user)
        else:
            self.params[mode] = param
    
    def remove_param(self, mode, param, user):
        method = getattr(self, "remove_param_%s" % mode, None)
        if method is not None:
            method(param, user)
        else:
            del self.params[mode]
    
    def combine(self, modes, params, user):
        changes = 0
        added = set()
        removed = set()
        bad = set()
        forbidden = set()
        current = added
        cur_param = self.add_param
        for mode in modes:
            if changes >= 20:
                break
            elif mode == '+':
                current = added
                cur_param = self.add_param
            elif mode == '-':
                current = removed
                cur_param = self.remove_param
            elif mode not in self.allowed_modes:
                bad.add(mode)
            elif self.perm_checker(mode):
                changes += 1
                current.add(mode)
                if mode in self.param_modes:
                    cur_param(mode, params.pop(0), user)
            else:
                forbidden.add(mode)
        old = self.modes.copy()
        self.modes.update(added)
        self.modes.difference_update(removed)
        added = self.modes - old
        removed = old - self.modes
        return added, removed, bad, forbidden

class UserModes(Modes):
    allowed_modes = "aiorsw" # http://tools.ietf.org/html/rfc2812#section-3.1.5
    param_modes = ""
    
    def perm_checker(self, mode):
        return mode != 'o' and mode != 'a' # r is handled by rejecting the mode command entirely