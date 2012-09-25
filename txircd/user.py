# -*- coding: utf-8 -*-

from twisted.words.protocols import irc
from twisted.internet.task import Cooperator
from txircd.mode import UserModes, ChannelModes
from txircd.utils import irc_lower, VALID_USERNAME
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
        self.ircd = parent.factory
        self.socket = parent
        self.nickname = nick
        self.username = username
        self.realname = realname
        self.hostname = parent.transport.getHandle().getpeername()[0]
        self.server = parent.factory.name
        self.oper = False
        self.away = False
        self.signon = time.time()
        self.lastactivity = time.time()
        self.mode = UserModes(self.ircd, self, mode, self.nickname)
        self.channels = []
        self.service = False
        
        self.ircd.users[self.nickname] = self
        
        chanmodes = ChannelModes.bool_modes + ChannelModes.string_modes + ChannelModes.hostmask_modes + self.ircd.prefix_order
        chanmodes2 = ChannelModes.hostmask_modes + ",," + ChannelModes.string_modes + "," + ChannelModes.bool_modes
        self.socket.sendMessage(irc.RPL_WELCOME, "%s :Welcome to the Internet Relay Network %s!%s@%s" % (self.nickname, self.nickname, self.username, self.hostname), prefix=self.socket.hostname)
        self.socket.sendMessage(irc.RPL_YOURHOST, "%s :Your host is %s, running version %s" % (self.nickname, self.ircd.name, self.ircd.version), prefix=self.socket.hostname)
        self.socket.sendMessage(irc.RPL_CREATED, "%s :This server was created %s" % (self.nickname, self.ircd.created,), prefix=self.socket.hostname)
        self.socket.sendMessage(irc.RPL_MYINFO, "%s %s %s %s %s" % (self.nickname, self.ircd.name, self.ircd.version, self.mode.allowed(), chanmodes), prefix=self.socket.hostname) # usermodes & channel modes
        self.socket.sendMessage(irc.RPL_ISUPPORT, "%s CASEMAPPING=rfc1459 CHANMODES=%s CHANTYPES=%s MODES=20 NICKLEN=32 PREFIX=(%s)%s STATUSMSG=%s :are supported by this server" % (self.nickname, chanmodes2, self.ircd.channel_prefixes, self.ircd.prefix_order, "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order]), "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])), prefix=self.socket.hostname)
    
    #=====================
    #== Utility Methods ==
    #=====================
    def prefix(self):
        return "%s!%s@%s" % (self.nickname, self.username, self.hostname)
    
    def accessLevel(self, channel):
        if channel not in self.channels or channel not in self.ircd.channels or not self.ircd.channels[channel]["users"][self.nickname]:
            return 0
        try:
            return len(self.ircd.prefix_order) - self.ircd.prefix_order.index(self.ircd.channels[channel]["users"][self.nickname][0])
        except:
            return 0
    
    def hasAccess(self, channel, level):
        if channel not in self.channels or channel not in self.ircd.channels:
            return None
        if not self.ircd.channels[channel]["users"][self.nickname]:
            return False
        try:
            return self.ircd.prefix_order.index(self.ircd.channels[channel]["users"][self.nickname][0]) <= self.ircd.prefix_order.index(level)
        except:
            return None
    
    def statusSort(self, status):
        s = ""
        for m in self.ircd.prefix_order:
            if m in status:
                s += m
        return s
    
    def report_names(self, channel):
        cdata = self.ircd.channels[channel]
        userlist = []
        if self.cap["multi-prefix"]:
            for user, ranks in cdata["users"].iteritems():
                name = ''
                for p in ranks:
                    name += self.ircd.PREFIX_SYMBOLS[p]
                name += self.ircd.users[user].nickname
                userlist.append(name)
        else:
            for user, ranks in cdata["users"].iteritems():
                if ranks:
                    userlist.append(self.ircd.prefix_symbols[ranks[0]] + self.ircd.users[user].nickname)
                else:
                    userlist.append(self.ircd.users[user].nickname)
        self.socket.names(self.nickname, channel, userlist)
    
    def join(self, channel, key):
        #TODO: Validate key
        if channel[0] not in self.ircd.channel_prefixes:
            return self.socket.sendMessage(irc.ERR_BADCHANMASK, "%s :Bad Channel Mask" % channel, prefix=self.socket.hostname)
        self.channels.append(channel)
        cdata = self.ircd.channels[channel]
        if not cdata["users"]:
            cdata["users"][self.nickname] = "o"
        else:
            cdata["users"][self.nickname] = ""
        for u in cdata["users"].iterkeys():
            self.ircd.users[u].socket.join(self.prefix(), channel)
        self.socket.topic(self.nickname, channel, cdata["topic"]["message"])
        if cdata["topic"]["message"] is not None:
            self.socket.topicAuthor(self.nickname, channel, cdata["topic"]["author"], cdata["topic"]["created"])
        self.report_names(channel)
    
    def part(self, channel, reason = None):
        self.channels.remove(channel)
        cdata = self.ircd.channels[channel]
        for u in cdata["users"].iterkeys():
            self.ircd.users[u].socket.part(self.prefix(), channel, reason)
        del cdata["users"][self.nickname]
        if not cdata["users"]:
            del self.ircd.channels[channel]
    
    def quit(self, channel, reason = None):
        self.channels.remove(channel)
        cdata = self.ircd.channels[channel]
        del cdata["users"][self.nickname]
        if not cdata["users"]:
            del self.ircd.channels[channel]
        else:
            for u in cdata["users"].iterkeys():
                self.ircd.users[u].socket.sendMessage("QUIT", ":%s" % reason, prefix=self.prefix())
    
    #======================
    #== Protocol Methods ==
    #======================
    def irc_PASS(self, prefix, params):
        self.socket.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.socket.hostname)
    
    def irc_PING(self, prefix, params):
        if params:
            self.socket.sendMessage("PONG", "%s :%s" % (self.socket.hostname, params[0]), prefix=self.socket.hostname)
        else:
            self.socket.sendMessage(irc.ERR_NOORIGIN, "%s :No origin specified" % self.nickname, prefix=self.socket.hostname)
    
    def irc_NICK(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.socket.hostname)
        elif params[0] in self.ircd.users:
            self.socket.sendMessage(irc.ERR_NICKNAMEINUSE, "%s :Nickname is already in use" % params[0], prefix=self.socket.hostname)
        elif not VALID_USERNAME.match(params[0]):
            self.socket.sendMessage(irc.ERR_ERRONEUSNICKNAME, "%s :Erroneous nickname" % params[0], prefix=self.socket.hostname)
        else:
            oldnick = self.nickname
            newnick = params[0]
            # Out with the old, in with the new
            del self.ircd.users[oldnick]
            self.ircd.users[newnick] = self
            tomsg = set() # Ensure users are only messaged once
            tomsg.add(irc_lower(newnick))
            for c in self.channels:
                mode = self.ircd.channels[c]["users"][oldnick]
                del self.ircd.channels[c]["users"][oldnick]
                self.ircd.channels[c]["users"][newnick] = mode
                for u in self.ircd.channels[c]["users"].iterkeys():
                    tomsg.add(u)
            for u in tomsg:
                self.ircd.users[u].socket.sendMessage("NICK", newnick, prefix=self.prefix())
            self.nickname = newnick
    
    def irc_USER(self, prefix, params):
        self.socket.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.socket.hostname)
    
    def irc_OPER(self, prefix, params):
        if len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER :Not enough parameters", prefix=self.socket.hostname)
        elif self.hostname not in self.ircd.oper_hosts:
            self.socket.sendMessage(irc.ERR_NOOPERHOST, "%s :No O-lines for your host" % self.nickname, prefix=self.socket.hostname)
        elif params[0] not in self.ircd.opers or self.ircd.opers[params[0]] != params[1]:
            self.socket.sendMessage(irc.ERR_PASSWDMISMATCH, "%s :Password incorrect" % self.nickname, prefix=self.socket.hostname)
        else:
            self.oper = True
            self.socket.sendMessage(irc.RPL_YOUREOPER, "%s :You are now an IRC operator" % self.nickname, prefix=self.socket.hostname)
    
    def irc_QUIT(self, prefix, params):
        reason = params[0] if params else "Client exited"
        for c in self.channels:
            self.quit(c,reason)
        del self.ircd.users[self.nickname]
        self.socket.sendMessage("ERROR","Closing Link: %s" % self.prefix())
        self.socket.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN :Not enough parameters", prefix=self.socket.hostname)
        elif params[0] == "0":
            for c in self.channels:
                self.part(c)
        else:
            channels = params[0].split(',')
            keys = params[1].split(',') if len(params) > 1 else []
            for i in range(len(channels)):
                c = channels[i]
                k = keys[i] if i < len(keys) else None
                assert c not in self.channels, "User '%s' already in channel '%s'" % (self.nickname, c)
                self.join(c,k)

    def irc_PART(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART :Not enough parameters", prefix=self.socket.hostname)
        channels = params[0].split(',')
        reason = params[1] if len(params) > 1 else self.nickname
        for c in channels:
            self.part(c, reason)
    
    def irc_MODE(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE :Not enough parameters", prefix=self.socket.hostname)
        elif params[0] in self.ircd.users:
            self.irc_MODE_user(params)
        elif params[0] in self.ircd.channels:
            self.irc_MODE_channel(params)
        else:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, "%s %s :No such nick/channel" % (self.nickname, params[0]), prefix=self.socket.hostname)

    def irc_MODE_user(self, params):
        user = self.ircd.users[params[0]]
        if user.nickname != self.nickname and not self.mode.has("o"): # Not self and not an OPER
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s :Can't %s for other users" % (user.nickname, "view modes" if len(params) == 1 else "change mode"), prefix=self.socket.hostname)
        else:
            if len(params) == 1:
                self.socket.sendMessage(irc.RPL_UMODEIS, "%s %s" % (user.nickname, user.mode), prefix=self.socket.hostname)
            else:
                response, bad, forbidden = user.mode.combine(params[1], params[2:], self.nickname)
                if response:
                    self.socket.sendMessage("MODE", "%s %s" % (user.nickname, response))
                for mode in bad:
                    self.socket.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, "%s %s :is unknown mode char to me" % (user.nickname, mode), prefix=self.socket.hostname)
                for mode in forbidden:
                    self.socket.sendMessage(irc.ERR_NOPRIVILEGES, "%s :Permission Denied - Only operators may set user mode %s" % (user.nickname, mode), prefix=self.socket.hostname)

    def irc_MODE_channel(self, params):
        if len(params) == 1:
            self.irc_MODE_channel_show(params)
        elif self.hasAccess(params[0], "h"):
            self.irc_MODE_channel_change(params)
        elif len(params) == 2 and ('b' in params[1] or 'e' in params[1] or 'I' in params[1]):
            self.irc_MODE_channel_bans(params)
        else:
            self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You must have channel halfop access or above to set channel modes" % (self.nickname, params[0]), prefix=self.socket.hostname)

    def irc_MODE_channel_show(self, params):
        cdata = self.ircd.channels[params[0]]
        modeStr = str(cdata["mode"])
        self.socket.sendMessage(irc.RPL_CHANNELMODEIS, "%s %s +%s" % (self.nickname, cdata["name"], modeStr), prefix=self.socket.hostname)
        self.socket.sendMessage(irc.RPL_CREATIONTIME, "%s %s %d" % (self.nickname, cdata["name"], cdata["created"]), prefix=self.socket.hostname)
    
    def irc_MODE_channel_change(self, params):
        cdata = self.ircd.channels[params.pop(0)]
        modes, bad, forbidden = cdata["mode"].combine(params[0], params[1:], self.nickname)
        for mode in bad:
            self.socket.sendMessage(irc.ERR_UNKNOWNMODE, "%s %s :is unknown mode char to me" % (self.nickname, mode), prefix=self.socket.hostname)
        for mode in forbidden:
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, "%s :Permission denied - only operators may set mode %s" % (self.nickname, mode), prefix=self.socket.hostname)
        for nick in cdata["users"].iterkeys():
            u = self.ircd.users[nick]
            u.socket.sendMessage("MODE", "%s %s" % (cdata["name"], modes), prefix=self.prefix())

    def irc_MODE_channel_bans(self, params):
        cdata = self.ircd.channels[params[0]]
        if 'b' in params[1]:
            for banmask, settertime in cdata["bans"].iteritems():
                self.socket.sendMessage(irc.RPL_BANLIST, "%s %s %s %s %d" % (self.nickname, cdata["name"], banmask, settertime[0], settertime[1]), prefix=self.socket.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFBANLIST, "%s %s :End of channel ban list" % (self.nickname, cdata["name"]), prefix=self.socket.hostname)
        if 'e' in params[1]:
            for exceptmask, settertime in cdata["exemptions"].iteritems():
                self.socket.sendMessage(irc.RPL_EXCEPTLIST, "%s %s %s %s %d" % (self.nickname, cdata["name"], exceptmask, settertime[0], settertime[1]), prefix=self.socket.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFEXCEPTLIST, "%s %s :End of channel exception list" % (self.nickname, cdata["name"]), prefix=self.socket.hostname)
        if 'I' in params[1]:
            for invexmask, settertime in cdata["invites"].iteritems():
                self.socket.sendMessage(irc.RPL_INVITELIST, "%s %s %s %s %d" % (self.nickname, cdata["name"], invexmask, settertime[0], settertime[1]), prefix=self.socket.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFINVITELIST, "%s %s :End of channel invite exception list" % (self.nickname, cdata["name"]), prefix=self.socket.hostname)

    def irc_TOPIC(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s TOPIC :Not enough parameters" % self.nickname, prefix=self.socket.hostname)
            return
        if params[0] not in self.ircd.channels:
            self.socket.sendMessage(irc.ERR_NOSUCHCHANNEL, "%s %s :No such channel" % (self.nickname, params[0]), prefix=self.socket.hostname)
            return
        cdata = self.ircd.channels[params[0]]
        if len(params) == 1:
            self.socket.topic(self.nickname, cdata["name"], cdata["topic"]["message"])
            if cdata["topic"]["message"] is not None:
                self.socket.topicAuthor(self.nickname, cdata["name"], cdata["topic"]["author"], cdata["topic"]["created"])
        else:
            if self.nickname not in cdata["users"]:
                self.socket.sendMessage(irc.ERR_NOTONCHANNEL, "%s %s :You're not in that channel" % (self.nickname, cdata["name"]), prefix=self.socket.hostname)
            elif not cdata["mode"].has("t") or self.hasAccess(params[0],"h"):
                # If the channel is +t and the user has a rank that is halfop or higher, allow the topic change
                cdata["topic"] = {
                    "message": params[1],
                    "author": self.nickname,
                    "created": time.time()
                }
                for u in cdata["users"].iterkeys():
                    self.ircd.users[u].socket.topic(self.ircd.users[u].nickname, cdata["name"], params[1], self.prefix())
            else:
                self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, "%s %s :You do not have access to change the topic on this channel" % (self.nickname, cdata["name"]), prefix=self.socket.hostname)

    def irc_WHO(self, prefix, params):
        pass
    
    def irc_PRIVMSG(self, prefix, params):
        if len(params) < 2:
            return self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s PRIVMSG :Not enough parameters" % self.nickname, prefix=self.socket.hostname)
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.socket.privmsg(self.prefix(), u.nickname, message)
        elif target in self.ircd.channels:
            c = self.ircd.channels[target]
            # TODO: check for +m and status
            # TODO: check for +n
            for u in c["users"].iterkeys():
                if self.ircd.users[u].nickname is not self.nickname:
                    self.ircd.users[u].socket.privmsg(self.prefix(), c["name"], message)
    
    def irc_NOTICE(self, prefix, params):
        if len(params) < 2:
            return self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s NOTICE :Not enough parameters" % self.nickname, prefix=self.socket.hostname)
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.socket.notice(self.prefix(), u.nickname, message)
        elif target in self.ircd.channels:
            c = self.ircd.channels[target]
            # TODO: check for +m and status
            # TODO: check for +n
            for u in c["users"].iterkeys():
                if self.ircd.users[u].nickname is not self.nickname:
                    self.ircd.users[u].socket.notice(self.prefix(), c["name"], message)
    
    def irc_NAMES(self, prefix, params):
        #params[0] = channel list, params[1] = target server. We ignore the target
        channels = self.channels
        if params:
            channels = params[0].split(",")
        channels = filter(lambda x: x in self.channels and x in self.ircd.channels, channels)
        Cooperator().cooperate((self.report_names(c) for c in channels))
    
    def irc_LIST(self, prefix, params):
        #params[0] = channel list, params[1] = target server. We ignore the target
        channels = []
        if params:
            channels = filter(lambda x: x in self.ircd.channels, params[0].split(","))
        if not channels:
            channels = self.ircd.channels.keys()
        for c in channels:
            cdata = self.ircd.channels[c]
            self.socket.sendMessage(irc.RPL_LIST, "%s %s %d :%s" % (self.nickname, cdata["name"], len(cdata["users"]), cdata["topic"]["message"]), prefix=self.socket.hostname)
        self.socket.sendMessage(irc.RPL_LISTEND, "%s :End of /LIST" % self.nickname, prefix=self.socket.hostname)
    
    def irc_INVITE(self, prefix, params):
        if len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "%s INVITE :Not enough parameters" % self.nickname, prefix=self.socket.hostname)
        elif params[0] not in self.ircd.users:
            self.socket.sendMessage(ERR_NOSUCHNICK, "%s :No such nick/channel" % params[0], prefix=self.socket.hostname)
        elif params[1] in self.ircd.users[params[0]].channels:
            self.socket.sendMessage(ERR_USERONCHANNEL, "%s %s :is already on channel" % (params[0], params[1]), prefix=self.socket.hostname)
        elif params[1] in self.ircd.channels and params[1] not in self.channels:
            self.socket.sendMessage(ERR_NOTONCHANNEL, "%s :You're not on that channel" % params[1], prefix=self.socket.hostname)
        elif params[1] in self.ircd.channels and self.ircd.channels[params[1]]["mode"].has("i") and not self.chanLevel("h"):
            self.socket.sendMessage(ERR_CHANOPRIVSNEEDED, "%s :You're not channel operator" % params[1], prefix=self.socket.hostname)
        elif self.ircd.users[params[0]].mode.has("a"):
            self.socket.sendMessage(RPL_AWAY, "%s :%s" % (params[0], self.ircd.users[params[0]].mode.get("a")), prefix=self.socket.hostname)
        else:
            u = self.parent.factory.users[params[0]]
            self.socket.sendMessage(RPL_INVITING, "%s %s" % (params[1], u.nickname), prefix=self.parent.hostname)
            u.socket.sendMessage("INVITE", "%s %s" % (u.nickname, params[1]), prefix=self.prefix())
    
    def irc_unknown(self, prefix, command, params):
        self.socket.sendMessage(irc.ERR_UNKNOWNCOMMAND, "%s :Unknown command" % command, prefix=self.socket.hostname)
        raise NotImplementedError(command, prefix, params)
