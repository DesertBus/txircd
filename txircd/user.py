# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
import time

class IRCUser(object):
    cap = {
        "multi-prefix": False
    }
    
    def __init__(self, parent, user, password, nick):
        password = password[0] if password else None
        username = user[0]
        # RFC 2812 allows setting modes in the USER command but RFC 1459 does not
        mode = ""
        try:
            m = int(user[1])
            mode += "w" if m & 4 else ""
            mode += "i" if m & 8 else ""
        except ValueError:
            pass
        realname = user[3]
        assert nick not in parent.factory.users, "Nickname in use"
        #TODO: Check password
        self.parent = parent
        self.data = self.parent.factory.users[nick] = {
            "socket": parent,
            "nickname": nick,
            "username": username,
            "realname": realname,
            "hostname": parent.transport.getHandle().getpeername()[0],
            "server": parent.factory.name,
            "oper": False,
            "away": False,
            "signon": time.time(),
            "lastactivity": time.time(),
            "mode": mode,
            "channels": [],
            "service": False
        }
        self.parent.sendMessage(irc.RPL_WELCOME, "%s :Welcome to the Internet Relay Network %s!%s@%s" % (self.data["nickname"], self.data["nickname"], self.data["username"], self.data["hostname"]), prefix=self.parent.hostname)
        self.parent.sendMessage(irc.RPL_YOURHOST, "%s :Your host is %s, running version %s" % (self.data["nickname"], self.parent.factory.name, self.parent.factory.version), prefix=self.parent.hostname)
        self.parent.sendMessage(irc.RPL_CREATED, "%s :This server was created %s" % (self.data["nickname"], self.parent.factory.created,), prefix=self.parent.hostname)
        self.parent.sendMessage(irc.RPL_MYINFO, "%s %s %s %s %s" % (self.data["nickname"], self.parent.factory.name, self.parent.factory.version, self.parent.factory.usermodes, "".join(self.parent.factory.chanmodes)), prefix=self.parent.hostname) # usermodes & channel modes
        self.parent.sendMessage(irc.RPL_ISUPPORT, "%s CASEMAPPING=rfc1459 CHANMODES=%s CHANTYPES=%s MODES=20 PREFIX=(%s)%s STATUSMSG=%s :are supported by this server" % (self.data["nickname"], ",".join(self.parent.factory.chanmodes), self.parent.factory.channel_prefixes, self.parent.factory.PREFIX_ORDER, "".join([self.parent.factory.PREFIX_SYMBOLS[mode] for mode in self.parent.factory.PREFIX_ORDER]), "".join([self.parent.factory.PREFIX_SYMBOLS[mode] for mode in self.parent.factory.PREFIX_ORDER])), prefix=self.parent.hostname)
    
    #=====================
    #== Utility Methods ==
    #=====================
    def prefix(self):
        return "%s!%s@%s" % (self.data["nickname"], self.data["username"], self.data["hostname"])
    
    def join(self, channel, key):
        #TODO: Validate key
        # TODO: check channel limit
        # TODO: check channel bans and exceptions
        # TODO: check invite only and invite status
        if channel[0] not in self.parent.factory.channel_prefixes:
            return self.parent.sendMessage(irc.ERR_BADCHANMASK, "%s :Bad Channel Mask" % channel, prefix=self.parent.hostname)
        self.data["channels"].append(channel)
        cdata = self.parent.factory.channels[channel]
        if not cdata["users"]:
            cdata["users"][self.data["nickname"]] = "o"
        else:
            cdata["users"][self.data["nickname"]] = ""
        for u in cdata["users"].iterkeys():
            self.parent.factory.users[u]["socket"].join(self.prefix(), channel)
        self.parent.topic(self.data["nickname"], channel, cdata["topic"]["message"])
        if cdata["topic"]["message"] is not None:
            self.parent.topicAuthor(self.data["nickname"], channel, cdata["topic"]["author"], cdata["topic"]["created"])
        userlist = []
        if self.cap["multi-prefix"]:
            for user, ranks in cdata["users"].iteritems():
                name = ''
                for p in ranks:
                    name += p
                name += self.parent.factory.users[user]["nickname"]
                userlist.append(name)
        else:
            for user, ranks in cdata["users"].iteritems():
                if ranks:
                    userlist.append(self.parent.factory.PREFIX_SYMBOLS[ranks[0]] + self.parent.factory.users[user]["nickname"])
                else:
                    userlist.append(self.parent.factory.users[user]["nickname"])
        self.parent.names(self.data["nickname"], channel, userlist)
    
    def part(self, channel, reason = None):
        self.data["channels"].remove(channel)
        cdata = self.parent.factory.channels[channel]
        for u in cdata["users"].iterkeys():
            self.parent.factory.users[u]["socket"].part(self.prefix(), channel, reason)
        del cdata["users"][self.data["nickname"]]
        if not cdata["users"]:
            del self.parent.factory.channels[channel]
    
    def quit(self, channel, reason = None):
        self.data["channels"].remove(channel)
        cdata = self.parent.factory.channels[channel]
        del cdata["users"][self.data["nickname"]]
        if not cdata["users"]:
            del self.parent.factory.channels[channel]
        else:
            for u in cdata["users"].iterkeys():
                self.parent.factory.users[u]["socket"].sendMessage("QUIT", ":%s" % reason, prefix=self.prefix())
    
    #======================
    #== Protocol Methods ==
    #======================
    def irc_PASS(self, prefix, params):
        self.parent.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.parent.hostname)
    
    def irc_PING(self, prefix, params):
        if params:
            self.parent.sendMessage("PONG", "%s :%s" % (self.parent.hostname, params[0]), prefix=self.parent.hostname)
        else:
            self.parent.sendMessage(irc.ERR_NOORIGIN, "%s :No origin specified" % self.data["nickname"], prefix=self.parent.hostname)
    
    def irc_NICK(self, prefix, params):
        if not params:
            self.parent.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.parent.hostname)
        elif params[0] in self.parent.factory.users:
            self.parent.sendMessage(irc.ERR_NICKNAMEINUSE, "%s :Nickname is already in use" % params[0], prefix=self.parent.hostname)
        else:
            oldnick = self.data["nickname"]
            newnick = params[0]
            # Out with the old, in with the new
            del self.parent.factory.users[oldnick]
            self.parent.factory.users[newnick] = self.data
            tomsg = set() # Ensure users are only messaged once
            for c in self.data["channels"]:
                mode = self.parent.factory.channels[c]["users"][oldnick]
                del self.parent.factory.channels[c]["users"][oldnick]
                self.parent.factory.channels[c]["users"][newnick] = mode
                for u in self.parent.factory.channels[c]["users"].iterkeys():
                    tomsg.add(u)
            for u in tomsg:
                self.parent.factory.users[u]["socket"].sendMessage("NICK", newnick, prefix=self.prefix())
            self.data["nickname"] = newnick
    
    def irc_QUIT(self, prefix, params):
        reason = params[0] if params else "Client exited"
        for c in self.data["channels"]:
            self.quit(c,reason)
        del self.parent.factory.users[self.data['nickname']]
        self.parent.sendMessage("ERROR","Closing Link: %s" % self.prefix())
        self.parent.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if not params:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN :Not enough parameters", prefix=self.parent.hostname)
        elif params[0] == "0":
            for c in self.data["channels"]:
                self.part(c)
        else:
            channels = params[0].split(',')
            keys = params[1].split(',') if len(params) > 1 else []
            for i in range(len(channels)):
                c = channels[i]
                k = keys[i] if i < len(keys) else None
                assert c not in self.data["channels"], "User '%s' already in channel '%s'" % (self.data["nickname"], c)
                self.join(c,k)

    def irc_PART(self, prefix, params):
        if not params:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART :Not enough parameters", prefix=self.parent.hostname)
        channels = params[0].split(',')
        reason = params[1] if len(params) > 1 else self.data['nickname']
        for c in channels:
            self.part(c, reason)
    
    def irc_MODE(self, prefix, params):
        if not params:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE :Not enough parameters", prefix=self.parent.hostname)
        elif params[0] in self.parent.factory.users:
            user = self.parent.factory.users[params[0]]
            if user["nickname"] != self.data["nickname"]:
                self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s :Can't %s for other users" % (self.data["nickname"], "view modes" if len(params) == 1 else "change mode"), prefix=self.parent.hostname)
            else:
                if len(params) == 1:
                    self.parent.sendMessage(irc.RPL_UMODEIS, "%s +%s" % (self.data["nickname"], self.data["mode"]), prefix=self.parent.hostname)
                else:
                    adding = True
                    changeCount = 0
                    responseStr = ''
                    responseAdding = None
                    for mode in params[1]:
                        if changeCount >= 20:
                            break
                        if mode == '+':
                            adding = True
                        elif mode == '-':
                            adding = False
                        elif mode not in self.parent.factory.usermodes:
                            self.parent.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, "%s %s :is unknown mode char to me" % (self.data["nickname"], mode), prefix=self.parent.hostname)
                        elif adding:
                            if mode == 'o':
                                self.parent.sendMessage(irc.ERR_NOPRIVILEGES, "%s :Permission Denied - Only operators may set user mode o" % self.data["nickname"], prefix=self.parent.hostname)
                            elif mode not in self.data["mode"]:
                                self.data["mode"] += mode
                                if responseAdding != '+':
                                    responseAdding = '+'
                                    responseStr += '+'
                                responseStr += mode
                                changeCount += 1
                        else:
                            if mode in self.data["mode"]:
                                self.data["mode"] = self.data["mode"].replace(mode, '')
                                if responseAdding != '-':
                                    responseAdding = '-'
                                    responseStr += '-'
                                responseStr += mode
                                changeCount += 1
                    if responseStr:
                        self.parent.sendMessage("MODE", "%s %s" % (self.data["nickname"], responseStr), prefix=self.prefix())
        elif params[0] in self.parent.factory.channels:
            cdata = self.parent.factory.channels[params[0]]
            if len(params) == 1:
                modeStr = cdata["mode"]
                modeParams = ''
                if cdata["password"]:
                    modeStr += 'k'
                    modeParams += ' ' + cdata["password"]
                if cdata["limit"]:
                    modeStr += 'l'
                    modeParams += ' ' + str(cdata["limit"])
                modeStr += modeParams
                self.parent.sendMessage(irc.RPL_CHANNELMODEIS, "%s %s +%s" % (self.data["nickname"], cdata["name"], modeStr), prefix=self.parent.hostname)
                self.parent.sendMessage("329", "%s %s %d" % (self.data["nickname"], cdata["name"], cdata["created"]), prefix=self.parent.hostname)
            elif self.data["nickname"] in cdata["users"] and cdata["users"][self.data["nickname"]] and self.parent.factory.PREFIX_ORDER.find(cdata["users"][self.data["nickname"]][0]) <= self.parent.factory.PREFIX_ORDER.find('h'):
                adding = True
                changeCount = 0
                propModes = ''
                propAdding = None
                propParams = []
                currParam = 2
                for mode in params[1]:
                    if changeCount >= 20:
                        break
                    if mode == '+':
                        adding = True
                    elif mode == '-':
                        adding = False
                    elif mode in self.parent.factory.PREFIX_ORDER:
                        if currParam >= len(params):
                            continue
                        if adding:
                            targetUser = params[currParam]
                            if targetUser in cdata["users"] and mode not in cdata["users"][targetUser]:
                                if self.parent.factory.PREFIX_ORDER.find(cdata["users"][self.data["nickname"]][0]) > self.parent.factory.PREFIX_ORDER.find(mode) or (targetUser in cdata["users"] and cdata["users"][targetUser] and self.parent.factory.PREFIX_ORDER.find(cdata["users"][self.data["nickname"]][0]) > self.parent.factory.PREFIX_ORDER.find(cdata["users"][targetUser][0])):
                                    self.parent.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You do not have access to use channel mode %s on that user" % (self.data["nickname"], cdata["name"], mode), prefix=self.parent.hostname)
                                else:
                                    if not cdata["users"][targetUser]:
                                        cdata["users"][targetUser] = mode
                                    else:
                                        statusList = list(cdata["users"][targetUser])
                                        inserted = False
                                        for i in range(0, len(statusList)):
                                            if self.parent.factory.PREFIX_ORDER.find(mode) < self.parent.factory.PREFIX_ORDER.find(statusList[i]):
                                                statusList.insert(i, mode)
                                                inserted = True
                                        if not inserted:
                                            statusList.append(mode)
                                        cdata["users"][targetUser] = "".join(statusList)
                                    if propAdding != '+':
                                        propAdding = '+'
                                        propModes += '+'
                                    propModes += mode
                                    propParams.append(params[currParam])
                                    changeCount += 1
                        else:
                            targetUser = params[currParam]
                            if targetUser in cdata["users"] and mode in cdata["users"][targetUser]:
                                if self.parent.factory.PREFIX_ORDER.find(cdata["users"][targetUser][0]) < self.parent.factory.PREFIX_ORDER.find(cdata["users"][self.data["nickname"]][0]):
                                    self.parent.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You do not have access to use channel mode %s on that user" % (self.data["nickname"], cdata["name"], mode), prefix=self.parent.hostname)
                                else:
                                    cdata["users"][targetUser] = cdata["users"][targetUser].replace(mode, '')
                                    if propAdding != '-':
                                        propAdding = '-'
                                        propModes += '-'
                                    propModes += mode
                                    propParams.append(params[currParam])
                                    changeCount += 1
                        currParam += 1
                    elif mode in self.parent.factory.chanmodes[0]:
                        if currParam >= len(params):
                            if mode == 'b':
                                for banmask, settertime in cdata["bans"].iteritems():
                                    self.parent.sendMessage(irc.RPL_BANLIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], banmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                                self.parent.sendMessage(irc.RPL_ENDOFBANLIST, "%s %s :End of channel ban list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
                            elif mode == 'e':
                                for exceptmask, settertime in cdata["exemptions"].iteritems():
                                    self.parent.sendMessage(irc.RPL_EXCEPTLIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], exceptmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                                self.parent.sendMessage(irc.RPL_ENDOFEXCEPTLIST, "%s %s :End of channel exception list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
                            elif mode == 'I':
                                for invexmask, settertime in cdata["invites"].iteritems():
                                    self.parent.sendMessage(irc.RPL_INVITELIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], invexmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                                self.parent.sendMessage(irc.RPL_ENDOFINVITELIST, "%s %s :End of channel invite exception list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
                            continue
                        change = None
                        hostmask = params[currParam]
                        # If we ever add a list mode that doesn't work on hostmasks, move this check to inside the +beI checks
                        if '!' not in hostmask:
                            if '@' in hostmask:
                                hostmask = '*!' + hostmask
                            else:
                                hostmask += "!*@*"
                        elif '@' not in hostmask:
                            hostmask += "@*"
                        if mode == 'b':
                            if adding and hostmask not in cdata["bans"]:
                                cdata["bans"][hostmask] = [self.data["nickname"], time.time()]
                                change = '+'
                            elif not adding and hostmask in cdata["bans"]:
                                del cdata["bans"][hostmask]
                                change = '-'
                        elif mode == 'e':
                            if adding and hostmask not in cdata["exemptions"]:
                                cdata["exemptions"][hostmask] = [self.data["nickname"], time.time()]
                                change = '+'
                            elif not adding and hostmask in cdata["exemptions"]:
                                del cdata["exemptions"][hostmask]
                                change = '-'
                        elif mode == 'I':
                            if adding and hostmask not in cdata["invites"]:
                                cdata["invites"][hostmask] = [self.data["nickname"], time.time()]
                                change = '+'
                            elif not adding and hostmask in cdata["invites"]:
                                del cdata["invites"][hostmask]
                                change = '-'
                        currParam += 1
                        if change:
                            if propAdding != change:
                                propAdding = change
                                propModes += change
                            propModes += mode
                            propParams.append(hostmask)
                            changeCount += 1
                    elif mode in self.parent.factory.chanmodes[1]:
                        if currParam >= len(params):
                            continue
                        if mode == 'k': # The channel password has its own channel data entry
                            if adding:
                                cdata["password"] = params[currParam]
                                if propAdding != '+':
                                    propAdding = '+'
                                    propModes += '+'
                                propModes += mode
                                propParams.append(params[currParam])
                                changeCount += 1
                            elif params[currParam] == cdata["password"]:
                                cdata["password"] = None
                                if propAdding != '-':
                                    propAdding = '-'
                                    propModes += '-'
                                propModes += mode
                                propParams.append(params[currParam])
                                changeCount += 1
                        # else: there aren't other param/param modes currently
                    elif mode in self.parent.factory.chanmodes[2]:
                        if mode == 'l': # The channel limit has its own channel data entry
                            if adding:
                                if currParam >= len(params):
                                    continue
                                try:
                                    newLimit = int(params[currParam])
                                    if newLimit > 0:
                                        cdata["params"] = newLimit
                                        if propAdding != '+':
                                            propAdding = '+'
                                            propModes += '+'
                                        propModes += mode
                                        propParams.append(params[currParam])
                                        changeCount += 1
                                except:
                                    pass # Don't bother processing anything if we get a non-number
                                currParam += 1
                            else:
                                cdata["params"] = None
                                if propAdding != '-':
                                    propAdding = '-'
                                    propModes += '-'
                                propModes += mode
                                changeCount += 1
                        # else: there aren't any other param modes currently
                    elif mode in self.parent.factory.chanmodes[3]:
                        if adding and mode not in cdata["mode"]:
                            cdata["mode"] += mode
                            if propAdding != '+':
                                propAdding = '+'
                                propModes += '+'
                            propModes += mode
                            changeCount += 1
                        elif not adding and mode in cdata["mode"]:
                            cdata["mode"] = cdata["mode"].replace(mode, '')
                            if propAdding != '-':
                                propAdding = '-'
                                propModes += '-'
                            propModes += mode
                            changeCount += 1
                    else:
                        self.parent.sendMessage(irc.ERR_UNKNOWNMODE, "%s %s :is unknown mode char to me" % (self.data["nickname"], mode), prefix=self.parent.hostname)
                if propModes:
                    modeStr = "%s %s" % (propModes, " ".join(propParams))
                    for user in cdata["users"].iterkeys():
                        self.parent.factory.users[user]["socket"].sendMessage("MODE", "%s %s" % (cdata["name"], modeStr), prefix=self.prefix())
            elif len(params) == 2 and ('b' in params[1] or 'e' in params[1] or 'I' in params[1]):
                if 'b' in params[1]:
                    for banmask, settertime in cdata["bans"].iteritems():
                        self.parent.sendMessage(irc.RPL_BANLIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], banmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                    self.parent.sendMessage(irc.RPL_ENDOFBANLIST, "%s %s :End of channel ban list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
                if 'e' in params[1]:
                    for exceptmask, settertime in cdata["exemptions"].iteritems():
                        self.parent.sendMessage(irc.RPL_EXCEPTLIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], exceptmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                    self.parent.sendMessage(irc.RPL_ENDOFEXCEPTLIST, "%s %s :End of channel exception list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
                if 'I' in params[1]:
                    for invexmask, settertime in cdata["invites"].iteritems():
                        self.parent.sendMessage(irc.RPL_INVITELIST, "%s %s %s %s %d" % (self.data["nickname"], cdata["name"], invexmask, settertime[0], settertime[1]), prefix=self.parent.hostname)
                    self.parent.sendMessage(irc.RPL_ENDOFINVITELIST, "%s %s :End of channel invite exception list" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
            else:
                self.parent.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You must have channel halfop access or above to set channel modes" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
        else:
            self.parent.sendMessage(irc.ERR_NOSUCHNICK, "%s %s :No such nick/channel" % (self.data["nickname"], params[0]), prefix=self.parent.hostname)
    
    def irc_TOPIC(self, prefix, params):
        if not params:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s TOPIC :Not enough parameters" % self.data["nickname"], prefix=self.parent.hostname)
            return
        if params[0] not in self.parent.factory.channels:
            self.parent.sendMessage(irc.ERR_NOSUCHCHANNEL, "%s %s :No such channel" % (self.data["nickname"], params[0]), prefix=self.parent.hostname)
            return
        cdata = self.parent.factory.channels[params[0]]
        if len(params) == 1:
            self.parent.topic(self.data["nickname"], cdata["name"], cdata["topic"]["message"])
            if cdata["topic"]["message"] is not None:
                self.parent.topicAuthor(self.data["nickname"], cdata["name"], cdata["topic"]["author"], cdata["topic"]["created"])
        else:
            if self.data["nickname"] not in cdata["users"]:
                self.parent.sendMessage(irc.ERR_NOTONCHANNEL, "%s %s :You're not in that channel" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)
            elif 't' not in cdata["mode"] or (cdata["users"][self.data["nickname"]] and self.parent.factory.PREFIX_ORDER.find(cdata["users"][self.data["nickname"]][0]) <= self.parent.factory.PREFIX_ORDER.find('h')):
                # If the channel is +t and the user has a rank that is halfop or higher, allow the topic change
                cdata["topic"] = {
                    "message": params[1],
                    "author": self.data["nickname"],
                    "created": time.time()
                }
                for u in cdata["users"].iterkeys():
                    self.parent.factory.users[u]["socket"].topic(self.parent.factory.users[u]["nickname"], cdata["name"], params[1], self.prefix())
            else:
                self.parent.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You do not have access to change the topic on this channel" % (self.data["nickname"], cdata["name"]), prefix=self.parent.hostname)

    def irc_WHO(self, prefix, params):
        pass
    
    def irc_PRIVMSG(self, prefix, params):
        try:
            target = params[0]
            message = params[1]
        except IndexError:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s PRIVMSG :Not enough parameters" % self.data["nickname"], prefix=self.parent.hostname)
            return
        if target in self.parent.factory.users:
            u = self.parent.factory.users[target]
            u["socket"].privmsg(self.prefix(), u["nickname"], message)
        elif target in self.parent.factory.channels:
            c = self.parent.factory.channels[target]
            # TODO: check for +m and status
            # TODO: check for +n
            for u in c["users"].iterkeys():
                if self.parent.factory.users[u]["nickname"] is not self.data["nickname"]:
                    self.parent.factory.users[u]["socket"].privmsg(self.prefix(), c["name"], message)
    
    def irc_NOTICE(self, prefix, params):
        try:
            target = params[0]
            message = params[1]
        except IndexError:
            self.parent.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s NOTICE :Not enough parameters" % self.data["nickname"], prefix=self.parent.hostname)
            return
        if target in self.parent.factory.users:
            u = self.parent.factory.users[target]
            u["socket"].notice(self.prefix(), u["nickname"], message)
        elif target in self.parent.factory.channels:
            c = self.parent.factory.channels[target]
            # TODO: check for +m and status
            # TODO: check for +n
            for u in c["users"].iterkeys():
                if self.parent.factory.users[u]["nickname"] is not self.data["nickname"]:
                    self.parent.factory.users[u]["socket"].notice(self.prefix(), c["name"], message)
    
    def irc_unknown(self, prefix, command, params):
        self.parent.sendMessage(irc.ERR_UNKNOWNCOMMAND, "%s :Unknown command" % command, prefix=self.parent.hostname)
        raise NotImplementedError(command, prefix, params)
