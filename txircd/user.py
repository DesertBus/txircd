# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
import time

class IRCUser(object):
    def __init__(self, parent, user, password, nick):
        password = password[0] if password else None
        nick = nick[0]
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
    
    def prefix(self):
        return "%s!%s@%s" % (self.data["nickname"], self.data["username"], self.data["hostname"])
    
    def join(self, channel, key):
        #TODO: Validate key
        #TODO: Validate channel prefix
        self.data["channels"].append(channel)
        cdata = self.parent.factory.channels[channel]
        if not cdata["users"]:
            cdata["prefixes"]["op"].append(self.data["nickname"])
        cdata["users"][self.data["nickname"]] = self.data
        for u in cdata["users"].itervalues():
            u["socket"].join(self.prefix(), channel)
        self.parent.topic(self.data["nickname"], channel, cdata["topic"]["message"])
        if cdata["topic"]["message"] is not None:
            self.parent.topicAuthor(self.data["nickname"], channel, cdata["topic"]["author"], cdata["topic"]["created"])
        self.parent.names(self.data["nickname"], channel, [u["nickname"] for u in cdata["users"].itervalues()])
    
    def part(self, channel, reason = None):
        self.data["channels"].remove(channel)
        cdata = self.parent.factory.channels[channel]
        for u in cdata["users"].itervalues():
            u["socket"].part(self.prefix(), channel, reason)
        for rankedUsers in cdata["prefixes"].itervalues():
            rankedUsers.remove(self.data["nickname"])
        del cdata["users"][self.data["nickname"]]
        if not cdata["users"]:
            del self.parent.factory.channels[channel]
    
    def quit(self, channel, reason = None):
        self.data["channels"].remove(channel)
        cdata = self.parent.factory.channels[channel]
        for rankedUsers in cdata["prefixes"].itervalues:
            rankedUsers.remove(self.data["nickname"])
        del cdata["users"][self.data["nickname"]]
        if not cdata["users"]:
            del self.parent.factory.channels[channel]
        else:
            for u in cdata["users"].itervalues():
                u["socket"].sendMessage("QUIT", ":%s" % reason, prefix=self.prefix())
    
    def irc_QUIT(self, prefix, params):
        reason = params[0] if params else "Client exited"
        for c in self.data["channels"]:
            self.quit(c,reason)
        del self.parent.factory.users[self.data['nickname']]
        self.parent.sendMessage("ERROR","Closing Link: %s" % self.prefix())
        self.parent.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if params[0] == "0":
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
        channels = params[0].split(',')
        reason = params[1] if len(params) > 1 else self.data['nickname']
        for c in channels:
            self.part(c, reason)
    
    def irc_MODE(self, prefix, params):
        pass

    def irc_WHO(self, prefix, params):
        pass
    
    def irc_PRIVMSG(self, prefix, params):
        target = params[0]
        message = params[1]
        if target in self.parent.factory.users:
            u = self.parent.factory.users[target]
            u["socket"].privmsg(self.prefix(), u["nickname"], message)
        elif target in self.parent.factory.channels:
            c = self.parent.factory.channels[target]
            for u in c["users"].itervalues():
                if u is not self.data:
                    u["socket"].privmsg(self.prefix(), c["name"], message)
    
    def irc_unknown(self, prefix, command, params):
        raise NotImplementedError(command, prefix, params)
