# -*- coding: utf-8 -*-

from txircd.utils import CaseInsensitiveDictionary
import time, copy

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
    
    def perm_checker(self, adding, mode, user, param = None):
        return True
    
    def prep_param(self, mode, param):
        return param
    
    def has(self, mode):
        return mode in self.modes and self.modes[mode]
    
    def get(self, mode):
        return self.modes[mode]
        
    def combine(self, modes, params, user):
        # State Variables
        old_modes = copy.deepcopy(self.modes)
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
                if self.perm_checker(adding,mode,user):
                    if mode not in self.modes or self.modes[mode] != adding:
                        changes += 1
                        self.modes[mode] = adding
                else:
                    forbidden.add(mode)
            elif mode in self.string_modes:
                if adding:
                    param = self.prep_param(mode, params.pop(0))
                else:
                    param = False
                if self.perm_checker(adding,mode,user,param):
                    if mode not in self.modes or self.modes[mode] != param:
                        changes += 1
                        self.modes[mode] = param
                else:
                    forbidden.add(mode)
            elif mode in self.list_modes:
                param = self.prep_param(mode, params.pop(0))
                if self.perm_checker(adding,mode,user,param):
                    if mode not in self.modes:
                        self.modes[mode] = CaseInsensitiveDictionary()
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
        if added[1:]:
            changed += " " + " ".join(added[1:])
        if removed[1:]:
            changed += " " + " ".join(removed[1:])
        # Return the changes
        return changed, bad, forbidden

class UserModes(Modes):
    bool_modes = "iorsw" # http://tools.ietf.org/html/rfc2812#section-3.1.5
    string_modes = "a"
    list_modes = ""
    
    def __str__(self):
        return Modes.__str__(self).split(" ")[0]
    
    def perm_checker(self, adding, mode, user, param = None):
        if mode == "a":
            return False
        if mode == "o" and adding:
            return False
        if mode == "r" and not adding:
            return False
        return True

class ChannelModes(Modes):
    bool_modes = "imnpst" # http://tools.ietf.org/html/rfc2811#section-4 
    string_modes = "kl"
    list_modes = "aqohv"+"beI"
    
    def perm_checker(self, adding, mode, user, param = None):
        # Always allow the channel to set modes.
        # This means the server can set modes without fear of rejection
        if user == self.parent["name"]:
            return True
        if mode in "aqohv":
            setter = self.ircd.users[user]
            getter = self.ircd.users[param]
            if param not in self.parent["users"]:
                return False # Can't set modes on somebody not in the channel
            if user not in self.parent["users"] and not setter.mode.has("o"):
                return False # Only opers can set modes without being in the channel
            if not adding and getter.mode.has("o"):
                return False # Can't demote opers, not that it matters
            if adding and not setter.hasAccess(self.parent["name"], mode):
                return False # Need the access to set the access
            if not adding and not setter.accessLevel(self.parent["name"]) > getter.accessLevel(self.parent["name"]):
                return False # Can only demote those below you
        if mode == "l":
            try:
                int(param)
            except:
                return False
        return True
    
    def prep_param(self, mode, param):
        if mode in "beI":
            return fix_hostmask(param)
        if mode == "l":
            return int(param)
        return param
