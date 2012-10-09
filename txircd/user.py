# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.task import Cooperator
from twisted.internet.defer import Deferred
from txircd.mode import UserModes, ChannelModes
from txircd.utils import irc_lower, DURATION_REGEX, VALID_USERNAME, now, epoch, CaseInsensitiveDictionary, chunk_message, strip_colors
from pbkdf2 import crypt
import fnmatch, socket, hashlib, os, sys

class IRCUser(object):
    cap = {
        "multi-prefix": False
    }
    
    def __init__(self, parent, user, password, nick):
        if nick in parent.factory.users:
            # Race condition, we checked their nick but now it is unavailable
            # Just give up and crash hard
            parent.sendMessage(irc.ERR_NICKNAMEINUSE, parent.factory.users[nick].nickname, ":Nickname is already in use", prefix=parent.factory.hostname)
            parent.sendMessage("ERROR",":Closing Link: {}".format(parent.factory.users[nick].nickname))
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
        ip = parent.transport.getPeer().host
        if ip in parent.factory.vhosts:
            hostname = parent.factory.vhosts[ip]
        else:
            try:
                hostname = socket.gethostbyaddr(ip)[0]
                index = hostname.find(ip)
                index = hostname.find(".") if index < 0 else index + len(ip)
                if index < 0:
                    # Give up
                    hostname = "tx{}.IP".format(hashlib.md5(ip).hexdigest()[12:20])
                else:
                    mask = "tx{}".format(hashlib.md5(hostname[:index]).hexdigest()[12:20])
                    hostname = "{}{}".format(mask, hostname[index:])
            except IOError:
                hostname = "tx{}.IP".format(hashlib.md5(ip).hexdigest()[12:20])
        
        # Set attributes
        self.ircd = parent.factory
        self.socket = parent
        self.nickname = nick
        self.username = username.lstrip("-")
        self.realname = realname
        self.hostname = hostname
        self.ip = ip
        self.server = parent.factory.name
        self.signon = now()
        self.lastactivity = now()
        self.mode = UserModes(self.ircd, self, mode, self.nickname)
        self.channels = CaseInsensitiveDictionary()
        self.invites = []
        self.service = False
        self.account = None
        self.disconnected = Deferred()
        
        if not self.matches_xline("E"):
            xline_match = self.matches_xline("G")
            if xline_match != None:
                self.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                self.socket.sendMessage("ERROR", ":Closing Link: {} [G:Lined: {}]".format(self.prefix(), xline_match), prefix=self.ircd.hostname)
                raise ValueError("Banned user")
            xline_match = self.matches_xline("K") # We're still here, so try the next one
            if xline_match:
                self.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                self.socket.sendMessage("ERROR", ":Closing Link: {} [K:Lined: {}]".format(self.prefix(), xline_match), prefix=self.ircd.hostname)
                raise ValueError("Banned user")
        
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
    
    def checkData(self, data):
        if data > self.ircd.max_data and not self.mode.has("o"):
            log.msg("Killing user '{}' for flooding".format(self.nickname))
            self.irc_QUIT(None,["Killed for flooding"])
    
    def connectionLost(self, reason):
        self.irc_QUIT(None,["Client connection lost"])
        self.disconnected.callback(None)
    
    def handleCommand(self, command, prefix, params):
        method = getattr(self, "irc_{}".format(command), None)
        if command != "PING" and command != "PONG":
            self.lastactivity = now()
        try:
            if method is not None:
                if self.mode.has("o") or self.matches_xline("E") or not self.matches_xline("SHUN") or command in ["PING", "PONG", "JOIN", "PART", "QUIT"]:
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
    
    def parse_duration(self, duration_string):
        """
        Parses a string duration given in 1y2w3d4h5m6s format
        returning the total number of seconds
        """
        try: # attempt to parse as a number of seconds if we get just a number before we go through the parsing process
            return int(duration_string)
        except:
            pass
        timeparts = DURATION_REGEX.match(duration_string).groupdict()
        mult_factor = {
            "years": 31557600, # 365.25 days to avoid leap year nonsense
            "weeks": 604800,
            "days": 86400,
            "hours": 3600,
            "minutes": 60,
            "seconds": 1
        }
        duration = 0
        for unit, amount in timeparts.iteritems():
            if amount is not None:
                try:
                    duration += int(amount) * mult_factor[unit]
                except:
                    pass
        return duration
    
    def add_xline(self, linetype, mask, duration, reason):
        if mask in self.ircd.xlines[linetype]:
            self.socket.sendMessage("NOTICE", self.nickname, ":*** Failed to add line for {}: already exists".format(mask), prefix=self.ircd.hostname)
        else:
            self.ircd.xlines[linetype][mask] = {
                "created": now(),
                "duration": duration,
                "setter": self.nickname,
                "reason": reason
            }
            self.socket.sendMessage("NOTICE", self.nickname, ":*** Added line {} on mask {}".format(linetype, mask), prefix=self.ircd.hostname)
            match_mask = irc_lower(mask)
            match_list = []
            for user in self.ircd.users.itervalues():
                usermask = self.ircd.xline_match[linetype].format(nick=irc_lower(user.nickname), ident=irc_lower(user.username), host=irc_lower(user.hostname), ip=irc_lower(user.ip))
                if fnmatch.fnmatch(usermask, match_mask):
                    match_list.append(user)
            applymethod = getattr(self, "applyline_{}".format(linetype), None)
            if applymethod is not None:
                applymethod(match_list, reason)
    
    def remove_xline(self, linetype, mask):
        if mask not in self.ircd.xlines[linetype]:
            self.socket.sendMessage("NOTICE", self.nickname, ":*** Failed to remove line for {}: not found in list".format(mask), prefix=self.ircd.hostname)
        else:
            del self.ircd.xlines[linetype][mask]
            self.socket.sendMessage("NOTICE", self.nickname, ":*** Removed line {} on mask {}".format(linetype, mask), prefix=self.ircd.hostname)
            removemethod = getattr(self, "removeline_{}".format(linetype), None)
            if removemethod is not None:
                removemethod()
    
    def applyline_G(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                user.irc_QUIT(None, ["G:Lined: {}".format(reason)])
    
    def applyline_K(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                user.irc_QUIT(None, ["K:Lined: {}".format(reason)])
    
    def applyline_Z(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                user.irc_QUIT(None, ["Z:Lined: {}".format(reason)])
    
    def applyline_Q(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o"):
                user.socket.sendMessage("NOTICE", self.nickname, ":{}".format(self.ircd.ban_msg), prefix=self.ircd.hostname)
                user.irc_QUIT(None, ["Q:Lined: {}".format(reason)])
    
    def removeline_E(self):
        matching_users = { "G": [], "K": [] }
        for user in self.ircd.users.itervalues():
            if user.matches_xline("E"):
                continue # user still matches different e:lines
            for linetype in matching_users.iterkeys():
                if user.matches_xline(linetype):
                    matches_xline[linetype].append(user)
        if matching_users["G"]:
            self.applyline_G(matching_users["G"], "Exception removed")
        if matching_users["K"]:
            self.applyline_K(matching_users["K"], "Exception removed")
    
    def matches_xline(self, linetype):
        usermask = self.ircd.xline_match[linetype].format(nick=irc_lower(self.nickname), ident=irc_lower(self.username), host=irc_lower(self.hostname), ip=irc_lower(self.ip))
        expired = []
        matched = None
        for mask, linedata in self.ircd.xlines[linetype].iteritems():
            if linedata["duration"] != 0 and epoch(now()) > epoch(linedata["created"]) + linedata["duration"]:
                expired.append(mask)
                continue
            if fnmatch.fnmatch(usermask, mask):
                matched = linedata["reason"]
                break # If there are more expired x:lines, they'll get removed later if necessary
        for mask in expired:
            del self.ircd.xlines[linetype][mask]
        # let expired lines properly clean up
        if expired:
            removemethod = getattr(self, "removeline_{}".format(linetype), None)
            if removemethod is not None:
                removemethod()
        return matched
    
    def send_motd(self):
        if self.ircd.motd:
            chunks = chunk_message(self.ircd.motd, self.ircd.motd_line_length)
            self.socket.sendMessage(irc.RPL_MOTDSTART, self.nickname, ":- {} Message of the day - ".format(self.ircd.name), prefix=self.ircd.hostname)
            for chunk in chunks:
                line = ":- {{:{!s}}} -".format(self.ircd.motd_line_length).format(chunk) # Dynamically inject the line length as a width argument for the line
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
        self.channels[cdata.name] = {"banned":banned,"exempt":exempt,"msg_rate":[]}
        if cdata.name in self.invites:
            self.invites.remove(cdata.name)
        if not cdata.users and self.ircd.founder_mode:
            cdata.mode.combine("+{}".format(self.ircd.founder_mode),[self.nickname],cdata.name) # Set first user as founder
        cdata.users[self.nickname] = self
        for u in cdata.users.itervalues():
            u.socket.sendMessage("JOIN", cdata.name, prefix=self.prefix())
        if cdata.topic["message"] is None:
            self.socket.sendMessage(irc.RPL_NOTOPIC, self.nickname, cdata.name, "No topic is set", prefix=self.ircd.hostname)
        else:
            self.socket.sendMessage(irc.RPL_TOPIC, self.nickname, cdata.name, ":{}".format(cdata.topic["message"]), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_TOPICWHOTIME, self.nickname, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])), prefix=self.ircd.hostname)
        self.report_names(cdata.name)
        cdata.log.write("[{:02d}:{:02d}:{:02d}] {} joined the channel\n".format(now().hour, now().minute, now().second, self.nickname))
    
    def leave(self, channel):
        cdata = self.ircd.channels[channel]
        cdata.log.write("[{:02d}:{:02d}:{:02d}] {} left the channel\n".format(now().hour, now().minute, now().second, self.nickname))
        mode = self.status(cdata.name) # Clear modes
        cdata.mode.combine("-{}".format(mode),[self.nickname for _ in mode],cdata.name)
        del self.channels[cdata.name]
        del cdata.users[self.nickname] # remove channel user entry
        if not cdata.users:
            del self.ircd.channels[cdata.name] # destroy the empty channel
            cdata.log.close()
    
    def part(self, channel, reason):
        for u in self.ircd.channels[channel].users.itervalues():
            u.socket.sendMessage("PART", self.ircd.channels[channel].name, ":{}".format(reason), prefix=self.prefix())
        self.leave(channel)
    
    def quit(self, channel, reason):
        for u in self.ircd.channels[channel].users.itervalues():
            u.socket.sendMessage("QUIT", ":{}".format(reason), prefix=self.prefix())
        self.leave(channel)
    
    def msg_cmd(self, cmd, params):
        if not params:
            return self.socket.sendMessage(irc.ERR_NORECIPIENT, self.nickname, ":No recipient given ({})".format(cmd), prefix=self.ircd.hostname)
        if len(params) < 2:
            return self.socket.sendMessage(irc.ERR_NOTEXTTOSEND, self.nickname, ":No text to send", prefix=self.ircd.hostname)
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.socket.sendMessage(cmd, u.nickname, ":{}".format(message), prefix=self.prefix())
        elif target in self.ircd.channels or target[1:] in self.ircd.channels:
            min_status = None
            if target[0] not in self.ircd.channel_prefixes:
                symbol_prefix = {v:k for k, v in self.ircd.prefix_symbols.items()}
                if target[0] not in symbol_prefix:
                    return self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, target, ":No such nick/channel", prefix=self.ircd.hostname)
                min_status = symbol_prefix[target[0]]
                target = target[1:]
            c = self.ircd.channels[target]
            if c.mode.has("n") and self.nickname not in c.users:
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (no external messages)", prefix=self.ircd.hostname)
            if c.mode.has("m") and not self.hasAccess(c.name, "v"):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (+m)", prefix=self.ircd.hostname)
            if self.channels[c.name]["banned"] and not (self.channels[c.name]["exempt"] or self.mode.has("o") or self.hasAccess(c.name, "v")):
                return self.socket.sendMessage(irc.ERR_CANNOTSENDTOCHAN, self.nickname, c.name, ":Cannot send to channel (banned)", prefix=self.ircd.hostname)
            if c.mode.has("S") and (not self.hasAccess(c.name, "h") or "S" not in self.ircd.exempt_chanops):
                message = strip_colors(message)
            if c.mode.has("f") and (not self.hasAccess(c.name, "h") or "f" not in self.ircd.exempt_chanops):
                nowtime = epoch(now())
                self.channels[c.name]["msg_rate"].append(nowtime)
                lines, seconds = c.mode.get("f").split(":")
                lines = int(lines)
                seconds = int(seconds)
                while self.channels[c.name]["msg_rate"] and self.channels[c.name]["msg_rate"][0] < nowtime - seconds:
                    self.channels[c.name]["msg_rate"].pop(0)
                if len(self.channels[c.name]["msg_rate"]) > lines:
                    for u in c.users.itervalues():
                        u.socket.sendMessage("KICK", c.name, self.nickname, ":Channel flood triggered ({} lines in {} seconds)".format(lines, seconds), prefix=self.ircd.hostname)
                    self.leave(c.name)
                    return
            # store the destination rather than generating it for everyone in the channel; show the entire destination of the message to recipients
            dest = "{}{}".format(self.ircd.prefix_symbols[min_status] if min_status else "", c.name)
            lines = chunk_message(message, 505-len(cmd)-len(dest)-len(self.prefix())) # Split the line up before sending it
            for u in c.users.itervalues():
                if u.nickname is not self.nickname and (not min_status or u.hasAccess(c.name, min_status)):
                    for l in lines:
                        u.socket.sendMessage(cmd, dest, ":{}".format(l), prefix=self.prefix())
            c.log.write("[{:02d}:{:02d}:{:02d}] {border_s}{nick}{border_e}: {message}\n".format(now().hour, now().minute, now().second, nick=self.nickname, message=message, border_s=("-" if cmd == "NOTICE" else "<"), border_e=("-" if cmd == "NOTICE" else ">")))
        else:
            return self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, target, ":No such nick/channel", prefix=self.ircd.hostname)
    
    def add_to_whowas(self):
        if self.nickname not in self.ircd.whowas:
            self.ircd.whowas[self.nickname] = []
        self.ircd.whowas[self.nickname].append({
            "nickname": self.nickname,
            "username": self.username,
            "realname": self.realname,
            "hostname": self.hostname,
            "ip": self.ip,
            "time": now()
        })
        self.ircd.whowas[self.nickname] = self.ircd.whowas[self.nickname][-self.ircd.whowas_limit:] # Remove old entries
    
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
    
    def irc_PONG(self, prefix, params):
        pass
    
    def irc_NICK(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given", prefix=self.ircd.hostname)
        elif params[0] in self.ircd.users and irc_lower(params[0]) != irc_lower(self.nickname): # Just changing case on your own nick is fine
            self.socket.sendMessage(irc.ERR_NICKNAMEINUSE, self.ircd.users[params[0]].nickname, ":Nickname is already in use", prefix=self.ircd.hostname)
        elif not VALID_USERNAME.match(params[0]):
            self.socket.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname", prefix=self.ircd.hostname)
        else:
            oldnick = self.nickname
            newnick = params[0]
            reserved_nick = self.matches_xline("Q")
            if reserved_nick:
                self.socket.sendMessage(irc.ERR_ERRONEUSNICKNAME, self.nickname, newnick, ":Invalid nickname: {}".format(reserved_nick), prefix=self.ircd.hostname)
                return
            # Add to WHOWAS before changing everything
            self.add_to_whowas()
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
                cdata.log.write("[{:02d}:{:02d}:{:02d}] {} is now known as {}\n".format(now().hour, now().minute, now().second, oldnick, newnick))
            for u in tomsg:
                self.ircd.users[u].socket.sendMessage("NICK", newnick, prefix=oldprefix)
    
    def irc_USER(self, prefix, params):
        self.socket.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)", prefix=self.ircd.hostname)
    
    def irc_OPER(self, prefix, params):
        if len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters", prefix=self.ircd.hostname)
        elif self.hostname not in self.ircd.oper_hosts:
            self.socket.sendMessage(irc.ERR_NOOPERHOST, self.nickname, ":No O-lines for your host", prefix=self.ircd.hostname)
        elif params[0] not in self.ircd.opers or self.ircd.opers[params[0]] != crypt(params[1],self.ircd.opers[params[0]]):
            self.socket.sendMessage(irc.ERR_PASSWDMISMATCH, self.nickname, ":Password incorrect", prefix=self.ircd.hostname)
        else:
            self.mode.modes["o"] = True
            self.socket.sendMessage(irc.RPL_YOUREOPER, self.nickname, ":You are now an IRC operator", prefix=self.ircd.hostname)
    
    def irc_QUIT(self, prefix, params):
        if not self.nickname in self.ircd.users:
            return # Can't quit twice
        self.add_to_whowas()
        reason = params[0] if params else "Client exited"
        for c in self.channels.keys():
            self.quit(c,reason)
        del self.ircd.users[self.nickname]
        self.socket.sendMessage("ERROR",":Closing Link: {} [{}]".format(self.prefix(), reason))
        self.socket.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters", prefix=self.ircd.hostname)
        elif params[0] == "0":
            for c in self.channels.keys():
                self.part(c, "Parting all channels")
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
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, ":Can't {} for other users".format("view modes" if len(params) == 1 else "change mode"), prefix=self.ircd.hostname)
        else:
            if len(params) == 1:
                self.socket.sendMessage(irc.RPL_UMODEIS, user.nickname, user.mode, prefix=self.ircd.hostname)
            else:
                response, bad, forbidden = user.mode.combine(params[1], params[2:], self.nickname)
                if response:
                    self.socket.sendMessage("MODE", user.nickname, response, prefix=self.prefix())
                    if user.nickname != self.nickname: # Also send the mode change to the user if an oper is changing it
                        user.socket.sendMessage("MODE", user.nickname, response, prefix=self.prefix())
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
            cdata.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, self.nickname, modes))
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
                    u.socket.sendMessage("TOPIC", u.nickname, cdata.name, ":{}".format(cdata.topic["message"]), prefix=self.prefix())
                cdata.log.write("[{:02d}:{:02d}:{:02d}] {} changed the topic to {}\n".format(now().hour, now().minute, now().second, self.nickname, params[1]))
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
        # When server-to-server is implemented, replace self.ircd.hostname in the replies with a way to get the (real or masked) server name for each user
        # We don't need to worry about fixing the hopcount since most IRCds always send 0
        if not params:
            for u in self.ircd.users.itervalues():
                if u.mode.has("i"):
                    continue
                common_channel = False
                for c in self.channels.iterkeys():
                    if c in u.channels:
                        common_channel = True
                        break
                if not common_channel:
                    self.socket.sendMessage(irc.RPL_WHOREPLY, self.nickname, "*", u.username, u.hostname, self.ircd.hostname, u.nickname, "{}{}".format("G" if u.mode.has("a") else "H", "*" if u.mode.has("o") else ""), ":0 {}".format(u.realname), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFWHO, self.nickname, "*", ":End of /WHO list.", prefix=self.ircd.hostname)
        else:
            filters = ""
            if len(params) >= 2:
                filters = params[1]
            if params[0] in self.ircd.channels:
                cdata = self.ircd.channels[params[0]]
                in_channel = cdata.name in self.channels # cache this value instead of searching self.channels every iteration
                for user in cdata.users.itervalues():
                    if (in_channel or not user.mode.has("i")) and ("o" not in filters or user.mode.has("o")):
                        self.socket.sendMessage(irc.RPL_WHOREPLY, self.nickname, cdata.name, user.username, user.hostname, self.ircd.hostname, user.nickname, "{}{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else "", self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - user.accessLevel(cdata.name)]] if user.accessLevel(cdata.name) > 0 else ""), ":0 {}".format(user.realname), prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_ENDOFWHO, self.nickname, cdata.name, ":End of /WHO list.", prefix=self.ircd.hostname)
            elif params[0][0] in self.ircd.channel_prefixes:
                self.socket.sendMessage(irc.RPL_ENDOFWHO, self.nickname, params[0], ":End of /WHO list.", prefix=self.ircd.hostname)
            else:
                for user in self.ircd.users.itervalues():
                    if not user.mode.has("i") and (fnmatch.fnmatch(irc_lower(user.nickname), irc_lower(params[0])) or fnmatch.fnmatch(irc_lower(user.hostname), irc_lower(params[0]))):
                        self.socket.sendMessage(irc.RPL_WHOREPLY, self.nickname, params[0], user.username, user.hostname, self.ircd.hostname, user.nickname, "{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else ""), ":0 {}".format(user.realname), prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_ENDOFWHO, self.nickname, params[0], ":End of /WHO list.", prefix=self.ircd.hostname)
                # params[0] is used here for the target so that the original glob pattern is returned
    
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
            self.socket.sendMessage(irc.RPL_WHOISUSER, self.nickname, udata.nickname, udata.username, udata.ip if self.mode.has("o") else udata.hostname, "*", ":{}".format(udata.realname), prefix=self.ircd.hostname)
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
            if udata.socket.secure:
                self.socket.sendMessage(irc.RPL_WHOISSECURE, self.nickname, udata.nickname, ":is using a secure connection", prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_WHOISIDLE, self.nickname, udata.nickname, str(epoch(now()) - epoch(udata.lastactivity)), str(epoch(udata.signon)), ":seconds idle, signon time", prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFWHOIS, self.nickname, udata.nickname, ":End of /WHOIS list.", prefix=self.ircd.hostname)
    
    def irc_WHOWAS(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NONICKNAMEGIVEN, self.nickname, ":No nickname given", prefix=self.ircd.hostname)
            return
        users = params[0].split(",")
        for uname in users:
            if uname not in self.ircd.whowas:
                self.socket.sendMessage(irc.ERR_WASNOSUCHNICK, self.nickname, uname, ":No such nick", prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_ENDOFWHOWAS, self.nickname, "*", ":End of /WHOWAS list.", prefix=self.ircd.hostname)
                continue
            history = self.ircd.whowas[uname]
            for u in history:
                self.socket.sendMessage(irc.RPL_WHOISUSER, self.nickname, u["nickname"], u["username"], u["ip"] if self.mode.has("o") else u["hostname"], "*", ":{}".format(u["realname"]), prefix=self.ircd.hostname)
                self.socket.sendMessage(irc.RPL_WHOISSERVER, self.nickname, u["nickname"], self.ircd.hostname, ":{}".format(u["time"]), prefix=self.ircd.hostname)
            self.socket.sendMessage(irc.RPL_ENDOFWHOWAS, self.nickname, uname, ":End of /WHOWAS list.", prefix=self.ircd.hostname)
            
    def irc_PRIVMSG(self, prefix, params):
        self.msg_cmd("PRIVMSG", params)
    
    def irc_NOTICE(self, prefix, params):
        self.msg_cmd("NOTICE", params)
    
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
    
    def irc_AWAY(self, prefix, params):
        if not params:
            if self.mode.has("a"):
                del self.mode.modes["a"]
            self.socket.sendMessage(irc.RPL_UNAWAY, self.nickname, ":You are no longer marked as being away", prefix=self.ircd.hostname)
        else:
            self.mode.modes["a"] = params[0]
            self.socket.sendMessage(irc.RPL_NOWAWAY, self.nickname, ":You have been marked as being away", prefix=self.ircd.hostname)
    
    def irc_KILL(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission Denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or len(params) < 2:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "KILL", ":Not enough parameters.", prefix=self.ircd.hostname)
        elif params[0] not in self.ircd.users:
            self.socket.sendMessage(irc.ERR_NOSUCHNICK, self.nickname, params[0], ":No such nick", prefix=self.ircd.hostname)
        else:
            udata = self.ircd.users[params[0]]
            udata.socket.sendMessage("KILL", udata.nickname, ":{} ({})".format(self.nickname, params[1]), prefix=self.ircd.hostname)
            udata.irc_QUIT(None, ["Killed by {} ({})".format(self.nickname, params[1])])
    
    def irc_GLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "GLINE", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("G", banmask)
        else:
            banmask = irc_lower(params[0])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("G", banmask, self.parse_duration(params[1]), params[2])
    
    def irc_KLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "KLINE", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("K", banmask)
        else:
            banmask = irc_lower(params[0])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("K", banmask, self.parse_duration(params[1]), params[2])
    
    def irc_ZLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "ZLINE", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            self.remove_xline("Z", params[0][1:])
        else:
            self.add_xline("Z", params[0], self.parse_duration(params[1]), params[2])
    
    def irc_ELINE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "ELINE", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("E", params[0][1:])
        else:
            banmask = irc_lower(params[0])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("E", banmask, self.parse_duration(params[1]), params[2])
    
    def irc_QLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "QLINE", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            self.remove_xline("Q", params[0][1:])
        else:
            nickmask = irc_lower(params[0])
            if VALID_USERNAME.match(nickmask.replace("*","").replace("?","a")):
                self.add_xline("Q", nickmask, self.parse_duration(params[1]), params[2])
            else:
                self.socket.sendMessage("NOTICE", self.nickname, ":*** Could not set Q:Line: invalid nickmask", prefix=self.ircd.hostname)
    
    def irc_SHUN(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "SHUN", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("SHUN", banmask)
        else:
            banmask = irc_lower(params[0])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("SHUN", banmask, self.parse_duration(params[1]), params[2])
    
    def irc_VERSION(self, prefix, params):
        self.socket.sendMessage(irc.RPL_VERSION, self.nickname, self.ircd.version, self.ircd.hostname, ":txircd", prefix=self.ircd.hostname)
    
    def irc_TIME(self, prefix, params):
        self.socket.sendMessage(irc.RPL_TIME, self.nickname, self.ircd.hostname, ":{}".format(now()), prefix=self.ircd.hostname)
    
    def irc_ADMIN(self, prefix, params):
        self.socket.sendMessage(irc.RPL_ADMINME, self.nickname, self.ircd.hostname, ":Administrative info", prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_ADMINLOC1, self.nickname, ":{}".format(self.ircd.admin_info_server), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_ADMINLOC2, self.nickname, ":{}".format(self.ircd.admin_info_organization), prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_ADMINEMAIL, self.nickname, ":{}".format(self.ircd.admin_info_person), prefix=self.ircd.hostname)
    
    def irc_INFO(self, prefix, params):
        self.socket.sendMessage(irc.RPL_INFO, self.nickname, ":txircd", prefix=self.ircd.hostname)
        self.socket.sendMessage(irc.RPL_ENDOFINFO, self.nickname, ":End of INFO list", prefix=self.ircd.hostname)
    
    def irc_REHASH(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        self.ircd.rehash()
        self.socket.sendMessage(irc.RPL_REHASHING, self.nickname, self.ircd.config, ":Rehashing", prefix=self.ircd.hostname)
    
    def irc_DIE(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not self.ircd.allow_die:
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - Server does not allow use of DIE command", prefix=self.ircd.hostname)
            return
        reactor.stop()
    
    def irc_RESTART(self, prefix, params):
        if not self.mode.has("o"):
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - You do not have the required operator privileges", prefix=self.ircd.hostname)
            return
        if not self.ircd.allow_die:
            self.socket.sendMessage(irc.ERR_NOPRIVILEGES, self.nickname, ":Permission denied - Server does not allow use of RESTART command", prefix=self.ircd.hostname)
            return
        def restart():
            os.execl(sys.executable, sys.executable, *sys.argv)
        reactor.addSystemEventTrigger("after", "shutdown", restart)
        reactor.stop()
    
    def irc_USERHOST(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "USERHOST", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        users = params[:5]
        reply_list = []
        for u in users:
            if u in self.ircd.users:
                udata = self.ircd.users[u]
                nick = udata.nickname
                oper = "*" if udata.mode.has("o") else ""
                away = "-" if udata.mode.has("a") else "+"
                host = "{}@{}".format(udata.username, udata.hostname)
                reply_list.append("{}{}={}{}".format(nick, oper, away, host))
        self.socket.sendMessage(irc.RPL_USERHOST, self.nickname, ":{}".format(" ".join(reply_list)), prefix=self.ircd.hostname)
    
    def irc_ISON(self, prefix, params):
        if not params:
            self.socket.sendMessage(irc.ERR_NEEDMOREPARAMS, self.nickname, "ISON", ":Not enough parameters", prefix=self.ircd.hostname)
            return
        reply = []
        for user in params:
            if user in self.ircd.users:
                reply.append(self.ircd.users[user].nickname)
        self.socket.sendMessage(irc.RPL_ISON, self.nickname, ":{}".format(" ".join(reply)), prefix=self.ircd.hostname)
    
    def irc_unknown(self, prefix, command, params):
        self.socket.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command", prefix=self.ircd.hostname)
        raise NotImplementedError(command, prefix, params)
