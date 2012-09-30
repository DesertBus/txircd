# -*- coding: utf-8 -*-

from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.task import Cooperator
from txircd.mode import UserModes, ChannelModes
from txircd.utils import irc_lower, VALID_USERNAME, now, epoch, CaseInsensitiveDictionary, chunk_message
import fnmatch, socket, hashlib

class IRCUser(object):
    cap = {
        "multi-prefix": False
    }
    
    def __init__(self, parent, user, password, nick):
        if nick in parent.factory.users:
            # Race condition, we checked their nick but now it is unavailable
            # Just give up and crash hard
            parent.sendMessage(irc.ERR_NICKNAMEINUSE, parent.factory.users[nick].nickname, ":Nickname is already in use", prefix=parent.factory.hostname)
            parent.sendMessage("ERROR","Closing Link: {}".format(parent.factory.users[nick].nickname))
            parent.transport.loseConnection()
            raise ValueError("Invalid nickname")
        # Parse USER params
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
        #TODO: Check password
        
        # Mask the IP
        ip = parent.transport.getHandle().getpeername()[0]
        if ip in parent.factory.vhosts:
            hostname = parent.factory.vhosts[ip]
        else:
            hostname = socket.gethostbyaddr(ip)[0]
            index = hostname.find(ip)
            index = hostname.find(".") if index < 0 else index + len(ip)
            if index < 0:
                # Give up
                log.msg("Gave up on {}, reverting to {}".format(hostname,ip))
                hostname = ip
            else:
                mask = "tx{}".format(hashlib.md5(hostname[:index]).hexdigest()[12:20])
                hostname = "{}{}".format(mask, hostname[index:])
        
        # Set attributes
        self.ircd = parent.factory
        self.socket = parent
        self.nickname = nick
        self.username = username
        self.realname = realname
        self.hostname = hostname
        self.server = parent.factory.name
        self.signon = now()
        self.lastactivity = now()
        self.mode = UserModes(self.ircd, self, mode, self.nickname)
        self.channels = CaseInsensitiveDictionary()
        self.invites = []
        self.service = False
        self.account = None
        
        # Add self to user list
        self.ircd.users[self.nickname] = self
        
        # Send all those lovely join messages
        chanmodes = ChannelModes.bool_modes + ChannelModes.string_modes + ChannelModes.list_modes
        chanmodes2 = ChannelModes.list_modes.translate(None, self.ircd.prefix_order) + ",," + ChannelModes.string_modes + "," + ChannelModes.bool_modes
        prefixes = "({}){}".format(self.ircd.prefix_order, "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order]))
        statuses = "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])
        self.socket.sendMessage(irc.RPL_WELCOME, self.nickname, ":Welcome to the Internet Relay Network {}".format(self.prefix()), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_YOURHOST, self.nickname, ":Your host is {}, running version {}".format(self.ircd.name, self.ircd.version), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_CREATED, self.nickname, ":This server was created {}".format(self.ircd.created), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_MYINFO, self.nickname, self.ircd.name, self.ircd.version, self.mode.allowed(), chanmodes, prefix=self.ircd.hostname) # usermodes & channel modes
        self.socket.sendMessage(irc.RPL_ISUPPORT, self.nickname, "CASEMAPPING=rfc1459", "CHANMODES={}".format(chanmodes2), "CHANTYPES={}".format(self.ircd.channel_prefixes), "MODES=20", "NICKLEN=32", "PREFIX={}".format(prefixes), "STATUSMSG={}".format(statuses), ":are supported by this server", prefix=self.ircd.hostname)
        self.send_motd()
    
    def connectionLost(self, reason):
        self.irc_QUIT(None,["Client connection lost"])
    
    def handleCommand(self, command, prefix, params):
        method = getattr(self, "irc_{}".format(command), None)
        if command != "PING" and command != "PONG":
            self.lastactivity = now()
        try:
            if method is not None:
                method(prefix, params)
            else:
                self.irc_unknown(prefix, command, params)
        except:
            log.deferr()
    
    #=====================
    #== Utility Methods ==
    #=====================
    def prefix(self):
        return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
    
    def accessLevel(self, channel):
        if channel not in self.channels or channel not in self.ircd.channels or self.nickname not in self.ircd.channels[channel].users:
            return 0
        modes = self.ircd.channels[channel].mode
        max = len(self.ircd.prefix_order)
        for level, mode in enumerate(self.ircd.prefix_order):
            if not modes.has(mode):
                continue
            if self.nickname in modes.get(mode):
                return max - level
        return 0
    
    def hasAccess(self, channel, level):
        if channel not in self.channels or channel not in self.ircd.channels or level not in self.ircd.prefix_order:
            return None
        if self.nickname not in self.ircd.channels[channel].users:
            return False
        access = len(self.ircd.prefix_order) - self.ircd.prefix_order.index(level)
        return self.accessLevel(channel) >= access
    
    def status(self, channel):
        if channel not in self.channels or channel not in self.ircd.channels or self.nickname not in self.ircd.channels[channel].users:
            return ""
        status = ""
        modes = self.ircd.channels[channel].mode
        for mode in self.ircd.prefix_order:
            if not modes.has(mode):
                continue
            if self.nickname in modes.get(mode):
                status += mode
        return status
    
    def send_motd(self):
        if self.ircd.motd:
            chunks = chunk_message(self.ircd.motd, self.ircd.motd_length)
            self.socket.sendMessage(irc.RPL_MOTDSTART, self.nickname, ":- {} Message of the day - ".format(self.ircd.name), prefix=self.ircd.hostname)
            for chunk in chunks:
                line = ":- {{:{!s}}} -".format(self.ircd.motd_length).format(chunk) # Dynamically inject the line length as a width argument for the line
                self.socket.sendMessage(irc.RPL_MOTD, self.nickname, line, prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFMOTD, self.nickname, ":End of MOTD command", prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage(irc.ERR_NOMOTD, self.nickname, ":MOTD File is missing", prefix=self.ircd.hostname)
    
    def report_names(self, channel):
        cdata = self.ircd.channels[channel]
        userlist = []
        if self.cap["multi-prefix"]:
            for user in cdata.users.itervalues():
                ranks = user.status(cdata.name)
                name = ""
                for p in ranks:
                    name += self.ircd.PREFIX_SYMBOLS[p]
                name += user.nickname
                userlist.append(name)
        else:
            for user in cdata.users.itervalues():
                ranks = user.status(cdata.name)
                if ranks:
                    userlist.append(self.ircd.prefix_symbols[ranks[0]] + user.nickname)
                else:
                    userlist.append(user.nickname)
        # Copy of irc.IRC.names
        prefixLength = len(self.ircd.hostname) + len(irc.RPL_NAMREPLY) + len(cdata.name) + len(self.nickname) + 10 # 10 characters for CRLF, =, : and spaces
        namesLength = 512 - prefixLength # May get messed up with unicode
        lines = chunk_message(" ".join(userlist), namesLength)
        for l in lines:
            self.socket.sendMessage(irc.RPL_NAMREPLY, self.nickname, "=", cdata.name, ":{}".format(l), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_ENDOFNAMES, self.nickname, cdata.name, ":End of /NAMES list", prefix=self.ircd.hostname)
    
    def join(self, channel, key):
        if channel[0] not in self.ircd.channel_prefixes:
            return self.socket.sendMessage(irc.ERR_BADCHANMASK, channel, ":Bad Channel Mask", prefix=self.ircd.hostname)
        cdata = self.ircd.channels[channel]
        cmodes = cdata.mode
        hostmask = irc_lower(self.prefix())
        banned = False
        exempt = False
        invited = cdata.name in self.invites
        if cmodes.has("b"):
            for pattern in cmodes.get("b").iterkeys():
                if fnmatch.fnmatch(hostmask, pattern):
                    banned = True
        if cmodes.has("e"):
            for pattern in cmodes.get("e").iterkeys():
                if fnmatch.fnmatch(hostmask, pattern):
                    exempt = True
        if not invited and cmodes.has("I"):
            for pattern in cmodes.get("I").iterkeys():
                if fnmatch.fnmatch(hostmask, pattern):
                    invited = True
        if cmodes.has("k") and cmodes.get("k") != key and not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_BADCHANNELKEY, self.nickname, cdata.name, ":Cannot join channel (Incorrect channel key)", prefix=self.ircd.hostname)
            return
        if cmodes.has("l") and cmodes.get("l") <= len(cdata.users) and not exempt and not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_CHANNELISFULL, self.nickname, cdata.name, ":Cannot join channel (Channel is full)", prefix=self.ircd.hostname)
            return
        if cmodes.has("i") and not invited and not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_INVITEONLYCHAN, self.nickname, cdata.name, ":Cannot join channel (Invite only)", prefix=self.ircd.hostname)
            return
        if banned and not exempt and not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_BANNEDFROMCHAN, self.nickname, cdata.name, ":Cannot join channel (Banned)", prefix=self.ircd.hostname)
            return
        self.channels[cdata.name] = {"banned":banned,"exempt":exempt}
        if cdata.name in self.invites:
            self.invites.remove(cdata.name)
        if not cdata.users:
            cdata.mode.combine("+q",[self.nickname],cdata.name) # Set first user as founder
        cdata.users[self.nickname] = self
        for u in cdata.users.itervalues():
            u.socket.sendMessage("JOIN", cdata.name, prefix=self.prefix())
        if cdata.topic["message"] is None:
            self.socket.sendMessage(irc.RPL_NOTOPIC, self.nickname, cdata.name, "No topic is set", prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage(irc.RPL_TOPIC, self.nickname, cdata.name, ":{}".format(cdata.topic["message"]), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_TOPICWHOTIME, self.nickname, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])), prefix=self.ircd.hostname)
        self.report_names(cdata.name)
    
    def leave(self, channel):
        cdata = self.ircd.channels[channel]
        del self.channels[cdata.name]
        del cdata.users[self.nickname] # remove channel user entry
        if not cdata.users:
            del self.ircd.channels[cdata.name] # destroy the empty channel
        else:
            mode = self.status(cdata.name) # Clear modes
            cdata.mode.combine("-{}".format(mode),[self.nickname for _ in mode],cdata.name)
    
    def part(self, channel, reason):
        for u in self.ircd.channels[channel].users.itervalues():
            u.socket.sendMessage("PART", self.ircd.channels[channel].name, ":{}".format(reason), prefix=self.prefix())
        self.leave(channel)
    
    def quit(self, channel, reason):
        for u in self.ircd.channels[channel].users.itervalues():
            u.socket.sendMessage("QUIT", ":{}".format(reason), prefix=self.prefix())
        self.leave(channel)
    
    #======================
    #== Protocol Methods ==
    #======================
    def irc_PASS(self, prefix, params):
        self.socket.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.ircd.hostname)
    
    def irc_PING(self, prefix, params):
        if params:
            self.socket.sendMessage("PONG", self.ircd.hostname, ":{}".format(params[0]), prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage(irc.ERR_NOORIGIN, self.nickname, ":No origin specified", prefix=self.ircd.hostname)
    
    def irc_NICK(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.ircd.hostname)
        elif params[0] in self.ircd.users and irc_lower(params[0]) != irc_lower(self.nickname): # Just changing case on your own nick is fine
            self.socket.sendMessage(irc.ERR_NICKNAMEINUSE, self.ircd.users[params[0]].nickname, ":Nickname is already in use", prefix=self.ircd.hostname)
        elif not VALID_USERNAME.match(params[0]):
            self.socket.sendMessage(irc.ERR_ERRONEUSNICKNAME, self.ircd.users[params[0]].nickname, ":Erroneous nickname", prefix=self.ircd.hostname)
        else:
            oldnick = self.nickname
            newnick = params[0]
            # Out with the old, in with the new
            del self.ircd.users[oldnick]
            self.ircd.users[newnick] = self
            tomsg = set() # Ensure users are only messaged once
            tomsg.add(irc_lower(newnick))
            # Prefix shenanigans
            oldprefix = self.prefix()
            self.nickname = newnick
            hostmask = irc_lower(self.prefix())
            for c in self.channels.iterkeys():
                cdata = self.ircd.channels[c]
                # Change reference in users map
                del cdata.users[oldnick]
                cdata.users[newnick] = self
                # Transfer modes
                mode = self.status(c)
                cdata.mode.combine("+{}".format(mode),[newnick for _ in mode],cdata.name)
                cdata.mode.combine("-{}".format(mode),[oldnick for _ in mode],cdata.name)
                # Update ban/exempt status
                banned = False
                exempt = False
                if cdata.mode.has("b"):
                    for pattern in cdata.mode.get("b").iterkeys():
                        if fnmatch.fnmatch(hostmask, pattern):
                            banned = True
                if cdata.mode.has("e"):
                    for pattern in cdata.mode.get("e").iterkeys():
                        if fnmatch.fnmatch(hostmask, pattern):
                            exempt = True
                self.channels[c] = {"banned":banned,"exempt":exempt}
                # Add channel members to message queue
                for u in self.ircd.channels[c].users.iterkeys():
                    tomsg.add(u)
            for u in tomsg:
                self.ircd.users[u].socket.sendMessage("NICK", newnick, prefix=oldprefix)
    
    def irc_USER(self, prefix, params):
        self.socket.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.ircd.hostname)
    
    def irc_OPER(self, prefix, params):
        if len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters", prefix=self.ircd.hostname)
        elif self.hostname not in self.ircd.oper_hosts:
            self.socket.sendMessage(irc.ERR_NOOPERHOST, self.nickname, ":No O-lines for your host", prefix=self.ircd.hostname)
        elif params[0] not in self.ircd.opers or self.ircd.opers[params[0]] != params[1]:
            self.socket.sendMessage(irc.ERR_PASSWDMISMATCH, self.nickname, ":Password incorrect", prefix=self.ircd.hostname)
        else:
            self.mode.modes["o"] = True
            self.socket.sendMessage(irc.RPL_YOUREOPER, self.nickname, ":You are now an IRC operator", prefix=self.ircd.hostname)
    
    def irc_QUIT(self, prefix, params):
        if not self.nickname in self.ircd.users:
            return # Can't quit twice
        reason = params[0] if params else "Client exited"
        for c in self.channels.keys():
            self.quit(c,reason)
        del self.ircd.users[self.nickname]
        self.socket.sendMessage("ERROR","Closing Link: {}".format(self.prefix()))
        self.socket.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters", prefix=self.ircd.hostname)
        elif params[0] == "0":
            for c in self.channels.keys():
                self.part(c)
        else:
            channels = params[0].split(",")
            keys = params[1].split(",") if len(params) > 1 else []
            for c in channels:
                if c in self.channels:
                    continue # don't join it twice
                cdata = self.ircd.channels[c]
                k = keys.pop(0) if keys and cdata.mode.has("k") else None
                self.join(c,k)

    def irc_PART(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters", prefix=self.ircd.hostname)
        channels = params[0].split(",")
        reason = params[1] if len(params) > 1 else self.nickname
        for c in channels:
            self.part(c, reason)
    
    def irc_MODE(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters", prefix=self.ircd.hostname)
        elif params[0] in self.ircd.users:
            self.irc_MODE_user(params)
        elif params[0] in self.ircd.channels:
            self.irc_MODE_channel(params)
        else:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, params[0], ":No such nick/channel", prefix=self.ircd.hostname)

    def irc_MODE_user(self, params):
        user = self.ircd.users[params[0]]
        if user.nickname != self.nickname and not self.mode.has("o"): # Not self and not an OPER
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, user.nickname, ":Can't {} for other users".format("view modes" if len(params) == 1 else "change mode"), prefix=self.ircd.hostname)
        else:
            if len(params) == 1:
                self.socket.sendMessage(irc.RPL_UMODEIS, user.nickname, user.mode, prefix=self.ircd.hostname)
            else:
                response, bad, forbidden = user.mode.combine(params[1], params[2:], self.nickname)
                if response:
                    self.socket.sendMessage("MODE", user.nickname, response)
                for mode in bad:
                    self.socket.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, user.nickname, mode, ":is unknown mode char to me", prefix=self.ircd.hostname)
                for mode in forbidden:
                    self.socket.sendMessage(irc.ERR_NOPRIVILEGES, user.nickname, ":Permission Denied - Only operators may set user mode {}".format(mode), prefix=self.ircd.hostname)

    def irc_MODE_channel(self, params):
        if len(params) == 1:
            self.irc_MODE_channel_show(params)
        elif len(params) == 2 and ("b" in params[1] or "e" in params[1] or "I" in params[1]):
            self.irc_MODE_channel_bans(params)
        elif self.hasAccess(params[0], "h") or self.mode.has("o"):
            self.irc_MODE_channel_change(params)
        else:
            self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, self.nickname, params[0], ":You must have channel halfop access or above to set channel modes", prefix=self.ircd.hostname)

    def irc_MODE_channel_show(self, params):
        cdata = self.ircd.channels[params[0]]
        self.socket.sendMessage(irc.RPL_CHANNELMODEIS, self.nickname, cdata.name, "+{!s}".format(cdata.mode), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_CREATIONTIME, self.nickname, cdata.name, str(epoch(cdata.created)), prefix=self.ircd.hostname)
    
    def irc_MODE_channel_change(self, params):
        cdata = self.ircd.channels[params.pop(0)]
        modes, bad, forbidden = cdata.mode.combine(params[0], params[1:], self.nickname)
        for mode in bad:
            self.socket.sendMessage(irc.ERR_UNKNOWNMODE, self.nickname, mode, ":is unknown mode char to me", prefix=self.ircd.hostname)
        for mode in forbidden:
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - only operators may set mode {}".format(mode), prefix=self.ircd.hostname)
        if modes:
            for u in cdata.users.itervalues():
                u.socket.sendMessage("MODE", cdata.name, modes, prefix=self.prefix())

    def irc_MODE_channel_bans(self, params):
        cdata = self.ircd.channels[params[0]]
        if "b" in params[1]:
            if cdata.mode.has("b"):
                for banmask, settertime in cdata.mode.get("b").iteritems():
                    self.socket.sendMessage(irc.RPL_BANLIST, self.nickname, cdata.name, banmask, settertime[0], str(epoch(settertime[1])), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFBANLIST, self.nickname, cdata.name, ":End of channel ban list", prefix=self.ircd.hostname)
        if "e" in params[1]:
            if cdata.mode.has("e"):
                for exceptmask, settertime in cdata.mode.get("e").iteritems():
                    self.socket.sendMessage(irc.RPL_EXCEPTLIST, self.nickname, cdata.name, exceptmask, settertime[0], str(epoch(settertime[1])), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFEXCEPTLIST, self.nickname, cdata.name, ":End of channel exception list", prefix=self.ircd.hostname)
        if "I" in params[1]:
            if cdata.mode.has("I"):
                for invexmask, settertime in cdata.mode.get("I").iteritems():
                    self.socket.sendMessage(irc.RPL_INVITELIST, self.nickname, cdata.name, invexmask, settertime[0], str(epoch(settertime[1])), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFINVITELIST, self.nickname, cdata.name, ":End of channel invite exception list", prefix=self.ircd.hostname)

    def irc_TOPIC(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "TOPIC", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0] not in self.ircd.channels:
            self.socket.sendMessage(irc.ERR_NOSUCHCHANNEL, self.nickname, params[0], ":No such channel", prefix=self.ircd.hostname)
            return
        cdata = self.ircd.channels[params[0]]
        if len(params) == 1:
            if cdata.topic["message"] is None:
                self.socket.sendMessage(irc.RPL_NOTOPIC, self.nickname, cdata.name, "No topic is set", prefix=self.ircd.hostname)
            else:
                self.socket.sendMessage(irc.RPL_TOPIC, self.nickname, cdata.name, ":{}".format(cdata.topic["message"]), prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_TOPICWHOTIME, self.nickname, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])), prefix=self.ircd.hostname)
        else:
            if self.nickname not in cdata.users:
                self.socket.sendMessage(irc.ERR_NOTONCHANNEL, self.nickname, cdata.name, ":You're not in that channel", prefix=self.ircd.hostname)
            elif not cdata.mode.has("t") or self.hasAccess(params[0],"h") or self.mode.has("o"):
                # If the channel is +t and the user has a rank that is halfop or higher, allow the topic change
                cdata.topic["message"] = params[1]
                cdata.topic["author"] = self.nickname
                cdata.topic["created"] = now()
                for u in cdata.users.itervalues():
                    u.socket.sendMessage(irc.RPL_TOPIC, u.nickname, cdata.name, ":{}".format(cdata.topic["message"]), prefix=self.prefix())
            else:
                self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, self.nickname, cdata.name, ":You do not have access to change the topic on this channel", prefix=self.ircd.hostname)
    
    def irc_KICK(self, prefix, params):
        if not params or len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "KICK", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if len(params) == 2:
            params.append(self.nickname) # default reason used on many IRCds
        if params[0] not in self.ircd.channels:
            self.socket.sendMessage(irc.ERR_NOSUCHCHANNEL, self.nickname, params[0], ":No such channel", prefix=self.ircd.hostname)
            return
        if params[1] not in self.ircd.users:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, params[1], ":No such nick", prefix=self.ircd.hostname)
            return
        cdata = self.ircd.channels[params[0]]
        udata = self.ircd.users[params[1]]
        if self.nickname not in cdata.users:
            self.socket.sendMessage(irc.ERR_NOTONCHANNEL, self.nickname, cdata["names"], ":You're not on that channel!", prefix=self.ircd.hostname)
            return
        if udata.nickname not in cdata.users:
            self.socket.sendMessage(irc.ERR_USERNOTINCHANNEL, self.nickname, udata.nickname, cdata.name, ":They are not on that channel", prefix=self.ircd.hostname)
            return
        if not self.hasAccess(params[0], "h") or (not self.accessLevel(params[0]) > udata.accessLevel(params[0]) and not self.mode.has("o")):
            self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, self.nickname, cdata.name, ":You must be a channel half-operator", prefix=self.ircd.hostname)
            return
        for u in cdata.users.itervalues():
            u.socket.sendMessage("KICK", cdata.name, udata.nickname, ":{}".format(params[2]), prefix=self.prefix())
        udata.leave(params[0])

    def irc_WHO(self, prefix, params):
        pass
    
    def irc_WHOIS(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NONICKNAMEGIVEN, self.nickname, ":No nickname given", prefix=self.ircd.hostname)
            return
        users = params[0].split(",")
        for uname in users:
            if uname not in self.ircd.users:
                self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, uname, ":No such nick/channel", prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_ENDOFWHOIS, self.nickname, "*", ":End of /WHOIS list.", prefix=self.ircd.hostname)
                continue
            udata = self.ircd.users[uname]
            self.socket.sendMessage(irc.RPL_WHOISUSER, self.nickname, udata.nickname, udata.username, udata.hostname, "*", ":{}".format(udata.realname), prefix=self.ircd.hostname)
            if udata.channels:
                chanlist = []
                for channel in udata.channels.iterkeys():
                    cdata = self.ircd.channels[channel]
                    if cdata.name in self.channels or (not cdata.mode.has("s") and not cdata.mode.has("p")):
                        level = udata.accessLevel(cdata.name)
                        if level == 0:
                            chanlist.append(cdata.name)
                        else:
                            symbol = self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - level]]
                            chanlist.append("{}{}".format(symbol, cdata.name))
                if chanlist:
                    self.socket.sendMessage(irc.RPL_WHOISCHANNELS, self.nickname, udata.nickname, ":{}".format(" ".join(chanlist)), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_WHOISSERVER, self.nickname, udata.nickname, self.ircd.hostname, ":{}".format(self.ircd.name), prefix=self.ircd.hostname)
            if udata.mode.has("a"):
                self.socket.sendMessage(irc.RPL_AWAY, self.nickname, udata.nickname, ":{}".format(udata.mode.get("a")), prefix=self.ircd.hostname)
            if udata.mode.has("o"):
                self.socket.sendMessage(irc.RPL_WHOISOPERATOR, self.nickname, udata.nickname, ":is an IRC operator", prefix=self.ircd.hostname)
            if udata.account:
                self.socket.sendMessage(irc.RPL_WHOISACCOUNT, self.nickname, udata.nickname, udata.account, ":is logged in as", prefix=self.ircd.hostname)
            # Numeric 671: Uncomment this when the secure check is done
            # if udata.socket.secure:
            #   self.socket.sendMessage(irc.RPL_WHOISSECURE, self.nickname, udata.nickname, ":is using a secure connection", prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_WHOISIDLE, self.nickname, udata.nickname, str(epoch(now()) - epoch(udata.lastactivity)), str(epoch(udata.signon)), ":seconds idle, signon time", prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFWHOIS, self.nickname, udata.nickname, ":End of /WHOIS list.", prefix=self.ircd.hostname)
    
    def irc_PRIVMSG(self, prefix, params):
        if not params:
            return self.socket.sendMessage(irc.ERR_NORECIPIENT, self.nickname, ":No recipient given (PRIVMSG)", prefix=self.ircd.hostname)
        if len(params) < 2:
            return self.socket.sendMessage(irc.ERR_NOTEXTTOSEND, self.nickname, ":No text to send", prefix=self.ircd.hostname)
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.socket.sendMessage("PRIVMSG", u.nickname, ":{}".format(message), prefix=self.prefix())
        elif target in self.ircd.channels:
            c = self.ircd.channels[target]
            if c.mode.has("n") and self.nickname not in c.users:
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (no external messages)", prefix=self.ircd.hostname)
            if c.mode.has("m") and not self.hasAccess(c.name, "v"):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (+m)", prefix=self.ircd.hostname)
            if self.channels[c.name]["banned"] and not (self.channels[c.name]["exempt"] or self.mode.has("o") or self.hasAccess(c.name, "v")):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (banned)", prefix=self.ircd.hostname)
            for u in c.users.itervalues():
                if u.nickname is not self.nickname:
                    u.socket.sendMessage("PRIVMSG", c.name, ":{}".format(message), prefix=self.prefix())
        else:
            return self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, target, ":No such nick/channel", prefix=self.ircd.hostname)
    
    def irc_NOTICE(self, prefix, params):
        if not params:
            return self.socket.sendMessage(irc.ERR_NORECIPIENT, self.nickname, ":No recipient given (NOTICE)", prefix=self.ircd.hostname)
        if len(params) < 2:
            return self.socket.sendMessage(irc.ERR_NOTEXTTOSEND, self.nickname, ":No text to send", prefix=self.ircd.hostname)
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.socket.sendMessage("NOTICE", u.nickname, ":{}".format(message), prefix=self.prefix())
        elif target in self.ircd.channels:
            c = self.ircd.channels[target]
            if c.mode.has("n") and self.nickname not in c.users:
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (no external messages)", prefix=self.ircd.hostname)
            if c.mode.has("m") and not self.hasAccess(c.name, "v"):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (+m)", prefix=self.ircd.hostname)
            if self.channels[c.name]["banned"] and not (self.channels[c.name]["exempt"] or self.mode.has("o") or self.hasAccess(c.name, "v")):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (banned)", prefix=self.ircd.hostname)
            for u in c.users.itervalues():
                if u.nickname is not self.nickname:
                    u.socket.sendMessage("NOTICE", c.name, ":{}".format(message), prefix=self.prefix())
        else:
            return self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, target, ":No such nick/channel", prefix=self.ircd.hostname)
    
    def irc_NAMES(self, prefix, params):
        #params[0] = channel list, params[1] = target server. We ignore the target
        channels = self.channels.keys()
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
            if self.nickname in cdata.users or (not cdata.mode.has("s") and not cdata.mode.has("p")):
                self.socket.sendMessage(irc.RPL_LIST, self.nickname, cdata.name, str(len(cdata.users)), ":{}".format(cdata.topic["message"]), prefix=self.ircd.hostname)
            elif cdata.mode.has("p") and not cdata.mode.has("s"):
                self.socket.sendMessage(irc.RPL_LIST, self.nickname, "*", str(len(cdata.users)), ":", prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_LISTEND, self.nickname, ":End of /LIST", prefix=self.ircd.hostname)
    
    def irc_INVITE(self, prefix, params):
        if len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "INVITE", ":Not enough parameters", prefix=self.ircd.hostname)
        elif params[0] not in self.ircd.users:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel", prefix=self.ircd.hostname)
        elif params[1] not in self.ircd.channels:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick/channel", prefix=self.ircd.hostname)
        
        udata = self.ircd.users[params[0]]
        cdata = self.ircd.channels[params[1]]
        if cdata.name in udata.channels:
            self.socket.sendMessage(irc.ERR_USERONCHANNEL, udata.nickname, cdata.name, ":is already on channel", prefix=self.ircd.hostname)
        elif cdata.name not in self.channels:
            self.socket.sendMessage(irc.ERR_NOTONCHANNEL,cdata.name, ":You're not on that channel", prefix=self.ircd.hostname)
        elif cdata.mode.has("i") and not self.hasAccess(cdata.name, "h"):
            self.socket.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You're not channel operator", prefix=self.ircd.hostname)
        elif udata.mode.has("a"):
            self.socket.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.mode.get("a")), prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage(irc.RPL_INVITING, cdata.name, udata.nickname, prefix=self.ircd.hostname)
            udata.socket.sendMessage("INVITE", udata.nickname, cdata.name, prefix=self.prefix())
            udata.invites.append(cdata.name)
    
    def irc_MOTD(self, prefix, params):
        self.send_motd()
    
    def irc_unknown(self, prefix, command, params):
        self.socket.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command", prefix=self.ircd.hostname)
        raise NotImplementedError(command, prefix, params)
