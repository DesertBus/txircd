# -*- coding: utf-8 -*-

def fix_hostmask(hostmask):
    if ' ' in hostmask:
        hostmask = hostmask[:hostmask.find(' ')]
    if '!' not in hostmask:
        if '@' in hostmask:
            hostmask = '*!' + hostmask
        else:
            hostmask += "!*@*"
    elif '@' not in hostmask:
        hostmask += "@*"
    return hostmask

class Modes(object):
    bool_modes = ""
    string_modes = ""
    list_modes = ""
    hostmask_modes = "" # Subset of list modes to run fix_hostmask on
    
    def __init__(self, ircd, parent, default_modes = None, user = None):
        self.modes = {}
        self.ircd = ircd
        self.parent = parent
        if default_modes is not None:
            params = default_modes.split(" ")
            self.combine(params[0], params[1:], user)

    def __str__(self):
        params = [""]
        for m in self.bool_modes:
            if m in self.modes and self.modes[m]:
                params[0] += m
        for m in self.string_modes:
            if m in self.modes and self.modes[m]:
                params[0] += m
                params.append(self.modes[m])
        return " ".join(params)

    def allowed(self):
        return self.bool_modes + self.string_modes + self.list_modes
    
    def perm_checker(self, mode, user):
        return True
    
    def has(self, mode):
        return mode in self.modes and self.modes[mode]
    
    def get(self, mode):
        return self.modes[mode]
        
    def combine(self, modes, params, user):
        # State Variables
        old_modes = self.modes.copy()
        changes = 0
        adding = True
        changed = ""
        bad = set()
        forbidden = set()
        # Change internal modes
        for mode in modes:
            if changes >= 20:
                break
            elif mode == '+':
                adding = True
            elif mode == '-':
                adding = False
            elif mode in self.bool_modes:
                if self.perm_checker(mode,user):
                    if mode not in self.modes or self.modes[mode] != adding:
                        changes += 1
                        self.modes[mode] = adding
                else:
                    forbidden.add(mode)
            elif mode in self.string_modes:
                if self.perm_checker(mode,user):
                    if adding:
                        param = params.pop(0)
                    else:
                        param = False
                    if mode not in self.modes or self.modes[mode] != param:
                        changes += 1
                        self.modes[mode] = param
                else:
                    forbidden.add(mode)
            elif mode in self.list_modes:
                if self.perm_checker(mode,user):
                    if mode not in self.modes:
                        self.modes[mode] = {}
                    param = params.pop(0)
                    if mode in self.hostmask_modes:
                        param = fix_hostmask(param) # Fix hostmask if it needs fixing
                    if adding:
                        if param not in self.modes[mode]:
                            changes += 1
                            self.modes[mode][param] = (user, time.time())
                    else:
                        if param in self.modes[mode]:
                            changes += 1
                            del self.modes[mode][param]
                else:
                    forbidden.add(mode)
            else:
                bad.add(mode)
        # Figure out what actually changed
        added = [""]
        removed = [""]
        for k, v in self.modes.iteritems():
            if k not in old_modes:
                if k in self.bool_modes:
                    if v:
                        added[0] += k
                elif k in self.string_modes:
                    if v:
                        added[0] += k
                        added.append(v)
                elif k in self.list_modes:
                    for n in v.iterkeys():
                        added[0] += k
                        added.append(n)
            else:
                if k in self.bool_modes:
                    if v == old_modes[k]:
                        continue
                    elif v:
                        added[0] += k
                    else:
                        removed[0] += k
                elif k in self.string_modes:
                    if v == old_modes[k]:
                        continue
                    elif v:
                        added[0] += k
                        added.append(v)
                    else:
                        removed[0] += k
                elif k in self.list_modes:
                    for n in v.iterkeys():
                        if n not in old_modes[k]:
                            added[0] += k
                            added.append(n)
                    for n in old_modes[k].iterkeys():
                        if n not in v:
                            removed[0] += k
                            removed.append(n)
        if added[0]:
            changed += "+"+added[0]
        if removed[0]:
            changed += "-"+removed[0]
        changed = ("%s %s %s" % (changed, " ".join(added[1:]), " ".join(removed[1:]))).strip()
        # Return the changes
        return changed, bad, forbidden

class UserModes(Modes):
    bool_modes = "iorsw" # http://tools.ietf.org/html/rfc2812#section-3.1.5
    string_modes = "a"
    list_modes = ""
    hostmask_modes = ""
    
    def perm_checker(self, mode, user):
        return mode != 'o' and mode != 'a' # r is handled by rejecting the mode command entirely

class ChannelModes(Modes):
    bool_modes = "imnst" # http://tools.ietf.org/html/rfc2811#section-4 
    string_modes = "kl"
    list_modes = "aqohv"+"beI"
    hostmask_modes = "beI"
    
    def perm_checker(self, mode, user):
        return True # What do
