from twisted.words.protocols import irc
from txircd.utils import now
from copy import deepcopy

class IRCChannel(object):
    def __init__(self, ircd, name):
        self.ircd = ircd
        self.name = name
        self.created = now()
        self.topic = ""
        self.topicSetter = ""
        self.topicTime = now()
        self.mode = deepcopy(self.ircd.servconfig["channel_default_mode"]) # If the user specifies default bans or other lists, references to those will still be problematic
        self.users = set()
        self.metadata = { # split into metadata key namespaces, see http://ircv3.atheme.org/specification/metadata-3.2
            "server": {},
            "user": {},
            "client": {},
            "ext": {},
            "private": {}
        }
        self.cache = {}
    
    def setMode(self, user, modes, params, override = False):
        adding = True
        currentParam = 0
        modeDisplay = []
        for mode in modes:
            if mode == "+":
                adding = True
            elif mode == "-":
                adding = False
            else:
                if mode not in self.ircd.channel_mode_type:
                    user.sendMessage(irc.ERR_UNKNOWNMODE, mode, ":is unknown mode char to me")
                    continue
                modetype = self.ircd.channel_mode_type[mode]
                if modetype == -1 or (modetype == 0 and len(params) > currentParam) or modetype == 1 or (adding and modetype == 2):
                    if len(params) <= currentParam:
                        continue # The mode must have a parameter, but one wasn't provided
                    param = params[currentParam]
                    currentParam += 1
                else:
                    param = None
                if not (modetype == 0 and param is None): # ignore these checks for list modes so that they can be listed
                    if not adding and modetype >= 0 and mode not in self.mode:
                        continue # The channel does not have the mode set, so we can't remove it
                    if modetype >= 0:
                        if adding:
                            allowed, param = self.ircd.channel_modes[modetype][mode].checkSet(user, self, param)
                            if not allowed:
                                continue
                        else:
                            allowed, param = self.ircd.channel_modes[modetype][mode].checkUnset(user, self, param)
                            if not allowed:
                                continue
                if modetype == -1:
                    if param not in self.ircd.users:
                        continue
                    udata = self.ircd.users[param]
                    if self.name not in udata.channels:
                        continue
                    if adding and mode in udata.status(self.name):
                        continue
                    if not adding and mode not in udata.status(self.name):
                        continue
                    if mode in self.ircd.servconfig["channel_status_minimum_change"]:
                        minimum_level = self.ircd.servconfig["channel_status_minimum_change"][mode]
                    else:
                        minimum_level = mode
                    if not adding and user == udata:
                        minimum_level = mode # Make the user always allowed to unset from self
                    if user.hasAccess(self.name, minimum_level) or override:
                        if adding:
                            allowed, param = self.ircd.prefixes[mode][2].checkSet(user, self, param)
                            if not allowed:
                                continue
                        else:
                            allowed, param = self.ircd.prefixes[mode][2].checkUnset(user, self, param)
                            if not allowed:
                                continue
                    else:
                        user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, self.name, ":You do not have the level required to change mode +{}".format(mode))
                        continue
                    if self.name not in udata.channels:
                        continue
                    if adding:
                        status = udata.channels[self.name]["status"]
                        statusList = list(status)
                        for index, statusLevel in enumerate(status):
                            if self.ircd.prefixes[statusLevel][1] < self.ircd.prefixes[mode][1]:
                                statusList.insert(index, mode)
                                break
                        if mode not in statusList: # no status to put this one before was found, so this goes at the end
                            statusList.append(mode)
                        udata.channels[self.name]["status"] = "".join(statusList)
                        modeDisplay.append([adding, mode, param])
                    else:
                        if mode in udata.channels[self.name]["status"]:
                            udata.channels[self.name]["status"] = udata.channels[self.name]["status"].replace(mode, "")
                            modeDisplay.append([adding, mode, param])
                elif modetype == 0:
                    if not param:
                        self.ircd.channel_modes[modetype][mode].showParam(user, self)
                    elif adding:
                        if mode not in self.mode:
                            self.mode[mode] = []
                        if param not in self.mode[mode]:
                            self.mode[mode].append(param)
                            modeDisplay.append([adding, mode, param])
                    else:
                        if mode not in self.mode:
                            continue
                        if param in self.mode[mode]:
                            self.mode[mode].remove(param)
                            modeDisplay.append([adding, mode, param])
                            if not self.mode[mode]:
                                del self.mode[mode]
                else:
                    if adding:
                        if mode in self.mode and param == self.mode[mode]:
                            continue
                        self.mode[mode] = param
                        modeDisplay.append([adding, mode, param])
                    else:
                        if mode not in self.mode:
                            continue
                        if modetype == 1 and param != self.mode[mode]:
                            continue
                        del self.mode[mode]
                        modeDisplay.append([adding, mode, param])
        if modeDisplay:
            adding = None
            modestring = []
            showParams = []
            for mode in modeDisplay:
                if mode[0] and adding != "+":
                    adding = "+"
                    modestring.append("+")
                elif not mode[0] and adding != "-":
                    adding = "-"
                    modestring.append("-")
                modestring.append(mode[1])
                if mode[2]:
                    showParams.append(mode[2])
            modeLine = "{} {}".format("".join(modestring), " ".join(showParams)) if showParams else "".join(modestring)
            for u in self.users:
                u.sendMessage("MODE", modeLine, to=self.name, prefix=user.prefix())
            return modeLine
        return ""
    
    def modeString(self, user):
        modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
        params = []
        for mode, param in self.mode.iteritems():
            modetype = self.ircd.channel_mode_type[mode]
            if modetype > 0:
                modes.append(mode)
                if param:
                    params.append(self.ircd.channel_modes[modetype][mode].showParam(user, self, param))
        return ("+{} {}".format("".join(modes), " ".join(params)) if params else "+{}".format("".join(modes)))
    
    def setTopic(self, topic, setter):
        for action in self.ircd.actions["topic"]:
            action(self, topic, setter)
        self.topic = topic
        self.topicSetter = setter
        self.topicTime = now()
    
    def setMetadata(self, namespace, key, value):
        oldValue = self.metadata[namespace][key] if key in self.metadata[namespace] else ""
        self.metadata[namespace][key] = value
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, value)
    
    def delMetadata(self, namespace, key):
        oldValue = self.metadata[namespace][key]
        del self.metadata[namespace][key]
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, "")