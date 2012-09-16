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
        self.parent.sendMessage(irc.RPL_MYINFO, "%s %s %s %s %s" % (self.data["nickname"], self.parent.factory.name, self.parent.factory.version, "iows", "bklmnopstv"), prefix=self.parent.hostname) # usermodes & channel modes
        self.parent.sendMessage(irc.RPL_ISUPPORT, "%s CASEMAPPING=rfc1459 CHANTYPES=%s PREFIX=(%s)%s STATUSMSG=%s :are supported by this server" % (self.data["nickname"], self.parent.factory.channel_prefixes, self.parent.factory.PREFIX_ORDER, "".join([self.parent.factory.PREFIX_SYMBOLS[mode] for mode in self.parent.factory.PREFIX_ORDER]), "".join([self.parent.factory.PREFIX_SYMBOLS[mode] for mode in self.parent.factory.PREFIX_ORDER])), prefix=self.parent.hostname)
    
    #=====================
    #== Utility Methods ==
    #=====================
    def prefix(self):
        return "%s!%s@%s" % (self.data["nickname"], self.data["username"], self.data["hostname"])
    
    def join(self, channel, key):
        #TODO: Validate key
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
        pass
    
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
            for u in c["users"].iterkeys():
                if self.parent.factory.users[u]["nickname"] is not self.data["nickname"]:
                    self.parent.factory.users[u]["socket"].notice(self.prefix(), c["name"], message)
    
    def irc_unknown(self, prefix, command, params):
        self.parent.sendMessage(irc.ERR_UNKNOWNCOMMAND, "%s :Unknown command" % command, prefix=self.parent.hostname)
        raise NotImplementedError(command, prefix, params)
