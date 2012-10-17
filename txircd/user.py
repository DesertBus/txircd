# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.defer import Deferred
from txircd.mode import UserModes, ChannelModes
from txircd.utils import irc_lower, parse_duration, VALID_USERNAME, now, epoch, CaseInsensitiveDictionary, chunk_message, strip_colors
from pbkdf2 import crypt
import fnmatch, socket, hashlib, collections, os, sys

class IRCUser(object):
    cap = {
        "multi-prefix": False
    }
    
    def __init__(self, parent, user, password, nick):
        if nick in parent.factory.users:
            # Race condition, we checked their nick but now it is unavailable
            # Just give up and crash hard
            parent.sendMessage(irc.ERR_NICKNAMEINUSE, parent.factory.users[nick].nickname, ":Nickname is already in use", prefix=parent.factory.server_name)
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
        if ip in parent.factory.client_vhosts:
            hostname = parent.factory.client_vhosts[ip]
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
        self.server = parent.factory.server_name
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
                self.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                self.sendMessage("ERROR", ":Closing Link: {} [G:Lined: {}]".format(self.prefix(), xline_match), to=None)
                raise ValueError("Banned user")
            xline_match = self.matches_xline("K") # We're still here, so try the next one
            if xline_match:
                self.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                self.sendMessage("ERROR", ":Closing Link: {} [K:Lined: {}]".format(self.prefix(), xline_match), to=None)
                raise ValueError("Banned user")
        
        # Add self to user list
        self.ircd.users[self.nickname] = self
        
        # Send all those lovely join messages
        chanmodes = ChannelModes.bool_modes + ChannelModes.string_modes + ChannelModes.list_modes
        chanmodes2 = ChannelModes.list_modes.translate(None, self.ircd.prefix_order) + ",," + ChannelModes.string_modes + "," + ChannelModes.bool_modes
        prefixes = "({}){}".format(self.ircd.prefix_order, "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order]))
        statuses = "".join([self.ircd.prefix_symbols[mode] for mode in self.ircd.prefix_order])
        self.sendMessage(irc.RPL_WELCOME, ":Welcome to the Internet Relay Network {}".format(self.prefix()))
        self.sendMessage(irc.RPL_YOURHOST, ":Your host is {}, running version {}".format(self.ircd.network_name, self.ircd.version))
        self.sendMessage(irc.RPL_CREATED, ":This server was created {}".format(self.ircd.created))
        self.sendMessage(irc.RPL_MYINFO, self.ircd.network_name, self.ircd.version, self.mode.allowed(), chanmodes) # usermodes & channel modes
        self.sendMessage(irc.RPL_ISUPPORT, "CASEMAPPING=rfc1459", "CHANMODES={}".format(chanmodes2), "CHANTYPES={}".format(self.ircd.channel_prefixes), "MODES=20", "NETWORK={}".format(self.ircd.network_name), "NICKLEN=32", "PREFIX={}".format(prefixes), "STATUSMSG={}".format(statuses), ":are supported by this server")
        self.send_motd()
    
    def checkData(self, data):
        if data > self.ircd.client_max_data and not self.mode.has("o"):
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
    
    def sendMessage(self, command, *parameter_list, **kw):
        if 'prefix' not in kw:
            kw['prefix'] = self.ircd.server_name
        if 'to' not in kw:
            kw['to'] = self.nickname
        if kw['to']:
            arglist = [command, kw['to']] + list(parameter_list)
        else:
            arglist = [command] + list(parameter_list)
        self.socket.sendMessage(*arglist, **kw)
    
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
    
    def add_xline(self, linetype, mask, duration, reason):
        if mask in self.ircd.xlines[linetype]:
            self.sendMessage("NOTICE", ":*** Failed to add line for {}: already exists".format(mask))
        else:
            self.ircd.xlines[linetype][mask] = {
                "created": now(),
                "duration": duration,
                "setter": self.nickname,
                "reason": reason
            }
            self.sendMessage("NOTICE", ":*** Added line {} on mask {}".format(linetype, mask))
            match_mask = irc_lower(mask)
            match_list = []
            for user in self.ircd.users.itervalues():
                usermasks = self.ircd.xline_match[linetype]
                for umask in usermasks:
                    usermask = umask.format(nick=irc_lower(user.nickname), ident=irc_lower(user.username), host=irc_lower(user.hostname), ip=irc_lower(user.ip))
                    if fnmatch.fnmatch(usermask, match_mask):
                        match_list.append(user)
                        break # break the inner loop to only match each user once
            applymethod = getattr(self, "applyline_{}".format(linetype), None)
            if applymethod is not None:
                applymethod(match_list, reason)
            self.ircd.save_options()
    
    def remove_xline(self, linetype, mask):
        if mask not in self.ircd.xlines[linetype]:
            self.sendMessage("NOTICE", ":*** Failed to remove line for {}: not found in list".format(mask))
        else:
            del self.ircd.xlines[linetype][mask]
            self.sendMessage("NOTICE", ":*** Removed line {} on mask {}".format(linetype, mask))
            removemethod = getattr(self, "removeline_{}".format(linetype), None)
            if removemethod is not None:
                removemethod()
            self.ircd.save_options()
    
    def applyline_G(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                user.irc_QUIT(None, ["G:Lined: {}".format(reason)])
    
    def applyline_K(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                user.irc_QUIT(None, ["K:Lined: {}".format(reason)])
    
    def applyline_Z(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o") and not user.matches_xline("E"):
                user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                user.irc_QUIT(None, ["Z:Lined: {}".format(reason)])
    
    def applyline_Q(self, userlist, reason):
        for user in userlist:
            if not user.mode.has("o"):
                user.sendMessage("NOTICE", ":{}".format(self.ircd.client_ban_msg))
                user.irc_QUIT(None, ["Q:Lined: {}".format(reason)])
    
    def removeline_E(self):
        matching_users = { "G": [], "K": [] }
        for user in self.ircd.users.itervalues():
            if user.matches_xline("E"):
                continue # user still matches different e:lines
            for linetype in matching_users.iterkeys():
                if user.matches_xline(linetype):
                    matching_users[linetype].append(user)
        if matching_users["G"]:
            self.applyline_G(matching_users["G"], "Exception removed")
        if matching_users["K"]:
            self.applyline_K(matching_users["K"], "Exception removed")
    
    def matches_xline(self, linetype):
        usermasks = self.ircd.xline_match[linetype]
        expired = []
        matched = None
        for mask, linedata in self.ircd.xlines[linetype].iteritems():
            if linedata["duration"] != 0 and epoch(now()) > epoch(linedata["created"]) + linedata["duration"]:
                expired.append(mask)
                continue
            for umask in usermasks:
                usermask = umask.format(nick=irc_lower(self.nickname), ident=irc_lower(self.username), host=irc_lower(self.hostname), ip=irc_lower(self.ip))
                if fnmatch.fnmatch(usermask, mask):
                    matched = linedata["reason"]
                    break # User only needs matched once.
            if matched:
                break # If there are more expired x:lines, they'll get removed later if necessary
        for mask in expired:
            del self.ircd.xlines[linetype][mask]
        # let expired lines properly clean up
        if expired:
            removemethod = getattr(self, "removeline_{}".format(linetype), None)
            if removemethod is not None:
                removemethod()
            self.ircd.save_options()
        return matched
    
    def send_motd(self):
        if self.ircd.server_motd:
            chunks = chunk_message(self.ircd.server_motd, self.ircd.server_motd_line_length)
            self.sendMessage(irc.RPL_MOTDSTART, ":- {} Message of the day - ".format(self.ircd.network_name))
            for chunk in chunks:
                line = ":- {{:{!s}}} -".format(self.ircd.server_motd_line_length).format(chunk) # Dynamically inject the line length as a width argument for the line
                self.sendMessage(irc.RPL_MOTD, line)
            self.sendMessage(irc.RPL_ENDOFMOTD, ":End of MOTD command")
        else:
            self.sendMessage(irc.ERR_NOMOTD, ":MOTD File is missing")
    
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
        prefixLength = len(self.ircd.server_name) + len(irc.RPL_NAMREPLY) + len(cdata.name) + len(self.nickname) + 10 # 10 characters for CRLF, =, : and spaces
        namesLength = 512 - prefixLength # May get messed up with unicode
        lines = chunk_message(" ".join(userlist), namesLength)
        for l in lines:
            self.sendMessage(irc.RPL_NAMREPLY, "=", cdata.name, ":{}".format(l))
        self.sendMessage(irc.RPL_ENDOFNAMES, cdata.name, ":End of /NAMES list")
    
    def join(self, channel, key):
        if channel[0] not in self.ircd.channel_prefixes:
            return self.sendMessage(irc.ERR_BADCHANMASK, channel, ":Bad Channel Mask")
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
            self.sendMessage(irc.ERR_BADCHANNELKEY, cdata.name, ":Cannot join channel (Incorrect channel key)")
            return
        if cmodes.has("l") and cmodes.get("l") <= len(cdata.users) and not exempt and not self.mode.has("o"):
            self.sendMessage(irc.ERR_CHANNELISFULL, cdata.name, ":Cannot join channel (Channel is full)")
            return
        if cmodes.has("i") and not invited and not self.mode.has("o"):
            self.sendMessage(irc.ERR_INVITEONLYCHAN, cdata.name, ":Cannot join channel (Invite only)")
            return
        if banned and not exempt and not self.mode.has("o"):
            self.sendMessage(irc.ERR_BANNEDFROMCHAN, cdata.name, ":Cannot join channel (Banned)")
            return
        self.channels[cdata.name] = {"banned":banned,"exempt":exempt,"msg_rate":[]}
        if cdata.name in self.invites:
            self.invites.remove(cdata.name)
        if not cdata.users and self.ircd.channel_founder_mode:
            cdata.mode.combine("+{}".format(self.ircd.channel_founder_mode),[self.nickname],cdata.name) # Set first user as founder
        cdata.users[self.nickname] = self
        for u in cdata.users.itervalues():
            u.sendMessage("JOIN", to=cdata.name, prefix=self.prefix())
        if cdata.topic["message"] is None:
            self.sendMessage(irc.RPL_NOTOPIC, cdata.name, "No topic is set")
        else:
            self.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic["message"]))
            self.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])))
        self.report_names(cdata.name)
        if not cdata.log.closed:
            cdata.log.write("[{:02d}:{:02d}:{:02d}] {} joined the channel\n".format(now().hour, now().minute, now().second, self.nickname))
    
    def leave(self, channel):
        cdata = self.ircd.channels[channel]
        if not cdata.log.closed:
            cdata.log.write("[{:02d}:{:02d}:{:02d}] {} left the channel\n".format(now().hour, now().minute, now().second, self.nickname))
        mode = self.status(cdata.name) # Clear modes
        cdata.mode.combine("-{}".format(mode),[self.nickname for _ in mode],cdata.name)
        del self.channels[cdata.name]
        del cdata.users[self.nickname] # remove channel user entry
        if not cdata.users:
            del self.ircd.channels[cdata.name] # destroy the empty channel
            cdata.log.close()
    
    def part(self, channel, reason):
        if channel not in self.ircd.channels:
            self.sendMessage(irc.ERR_NOSUCHCHANNEL, channel, ":No such channel")
            return
        cdata = self.ircd.channels[channel]
        if self.nickname not in cdata.users:
            self.sendMessage(irc.ERR_NOTONCHANNEL, channel, ":You're not on that channel")
            return
        for u in cdata.users.itervalues():
            u.sendMessage("PART", ":{}".format(reason), to=cdata.name, prefix=self.prefix())
        self.leave(channel)
    
    def quit(self, channel, reason):
        for u in self.ircd.channels[channel].users.itervalues():
            u.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
        self.leave(channel)
    
    def msg_cmd(self, cmd, params):
        if not params:
            return self.sendMessage(irc.ERR_NORECIPIENT, ":No recipient given ({})".format(cmd))
        if len(params) < 2:
            return self.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
        target = params[0]
        message = params[1]
        if target in self.ircd.users:
            u = self.ircd.users[target]
            u.sendMessage(cmd, ":{}".format(message), prefix=self.prefix())
        elif target in self.ircd.channels or target[1:] in self.ircd.channels:
            min_status = None
            if target[0] not in self.ircd.channel_prefixes:
                symbol_prefix = {v:k for k, v in self.ircd.prefix_symbols.items()}
                if target[0] not in symbol_prefix:
                    return self.sendMessage(irc.ERR_NOSUCHNICK, target, ":No such nick/channel")
                min_status = symbol_prefix[target[0]]
                target = target[1:]
            c = self.ircd.channels[target]
            if c.mode.has("n") and self.nickname not in c.users:
                return self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (no external messages)")
            if c.mode.has("m") and not self.hasAccess(c.name, "v"):
                return self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (+m)")
            if self.channels[c.name]["banned"] and not (self.channels[c.name]["exempt"] or self.mode.has("o") or self.hasAccess(c.name, "v")):
                return self.sendMessage(irc.ERR_CANNOTSENDTOCHAN, c.name, ":Cannot send to channel (banned)")
            if c.mode.has("S") and (not self.hasAccess(c.name, "h") or "S" not in self.ircd.channel_exempt_chanops):
                message = strip_colors(message)
            if c.mode.has("f") and (not self.hasAccess(c.name, "h") or "f" not in self.ircd.channel_exempt_chanops):
                nowtime = epoch(now())
                self.channels[c.name]["msg_rate"].append(nowtime)
                lines, seconds = c.mode.get("f").split(":")
                lines = int(lines)
                seconds = int(seconds)
                while self.channels[c.name]["msg_rate"] and self.channels[c.name]["msg_rate"][0] < nowtime - seconds:
                    self.channels[c.name]["msg_rate"].pop(0)
                if len(self.channels[c.name]["msg_rate"]) > lines:
                    for u in c.users.itervalues():
                        u.sendMessage("KICK", self.nickname, ":Channel flood triggered ({} lines in {} seconds)".format(lines, seconds), to=c.name)
                    self.leave(c.name)
                    return
            # store the destination rather than generating it for everyone in the channel; show the entire destination of the message to recipients
            dest = "{}{}".format(self.ircd.prefix_symbols[min_status] if min_status else "", c.name)
            lines = chunk_message(message, 505-len(cmd)-len(dest)-len(self.prefix())) # Split the line up before sending it
            msgto = set()
            for u in c.users.itervalues():
                if u.nickname is not self.nickname and (not min_status or u.hasAccess(c.name, min_status)):
                    msgto.add(u)
            for u in msgto:
                for l in lines:
                    u.sendMessage(cmd, ":{}".format(l), to=dest, prefix=self.prefix())
            if not c.log.closed:
                c.log.write("[{:02d}:{:02d}:{:02d}] {border_s}{nick}{border_e}: {message}\n".format(now().hour, now().minute, now().second, nick=self.nickname, message=message, border_s=("-" if cmd == "NOTICE" else "<"), border_e=("-" if cmd == "NOTICE" else ">")))
        else:
            return self.sendMessage(irc.ERR_NOSUCHNICK, target, ":No such nick/channel")
    
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
        self.ircd.whowas[self.nickname] = self.ircd.whowas[self.nickname][-self.ircd.client_whowas_limit:] # Remove old entries
    
    def stats_xline_list(self, xline_type, xline_numeric):
        for mask, linedata in self.ircd.xlines[xline_type].iteritems():
            self.sendMessage(xline_numeric, ":{} {} {} {} :{}".format(mask, epoch(linedata["created"]), linedata["duration"], linedata["setter"], linedata["reason"]))
    
    def stats_o(self):
        for user in self.ircd.users.itervalues():
            if user.mode.has("o"):
                self.sendMessage(irc.RPL_STATSOPERS, ":{} ({}@{}) Idle: {} secs".format(user.nickname, user.username, user.hostname, epoch(now()) - epoch(user.lastactivity)))
    
    def stats_p(self):
        if isinstance(self.ircd.server_port_tcp, collections.Sequence):
            for port in self.ircd.server_port_tcp:
                self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(port))
        else:
            self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(self.ircd.server_port_tcp))
        if isinstance(self.ircd.server_port_ssl, collections.Sequence):
            for port in self.ircd.server_port_ssl:
                self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(port))
        else:
            self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(self.ircd.server_port_ssl))
        if isinstance(self.ircd.server_port_web, collections.Sequence):
            for port in self.ircd.server_port_web:
                self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(port))
        else:
            self.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(self.ircd.server_port_web))
        # Add server ports here when we get s2s
    
    def stats_u(self):
        uptime = now() - self.ircd.created
        self.sendMessage(irc.RPL_STATSUPTIME, ":Server up {}".format(uptime if uptime.days > 0 else "0 days, {}".format(uptime)))
    
    def stats_G(self):
        self.stats_xline_list("G", irc.RPL_STATSGLINE)
    
    def stats_K(self):
        self.stats_xline_list("K", irc.RPL_STATSKLINE)
    
    def stats_Z(self):
        self.stats_xline_list("Z", irc.RPL_STATSZLINE)
    
    def stats_E(self):
        self.stats_xline_list("E", irc.RPL_STATSELINE)
    
    def stats_Q(self):
        self.stats_xline_list("Q", irc.RPL_STATSQLINE)
    
    def stats_S(self):
        self.stats_xline_list("SHUN", irc.RPL_STATSSHUN)
    
    #======================
    #== Protocol Methods ==
    #======================
    def irc_PASS(self, prefix, params):
        self.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
    
    def irc_PING(self, prefix, params):
        if params:
            self.sendMessage("PONG", ":{}".format(params[0]), to=self.ircd.server_name)
        else:
            self.sendMessage(irc.ERR_NOORIGIN, ":No origin specified")
    
    def irc_PONG(self, prefix, params):
        pass
    
    def irc_NICK(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
        elif params[0] in self.ircd.users and irc_lower(params[0]) != irc_lower(self.nickname): # Just changing case on your own nick is fine
            self.sendMessage(irc.ERR_NICKNAMEINUSE, self.ircd.users[params[0]].nickname, ":Nickname is already in use")
        elif not VALID_USERNAME.match(params[0]):
            self.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname")
        elif params[0] == self.nickname:
            pass # Don't send ERR_NICKNAMEINUSE if they're changing to exactly the nick they're already using
        else:
            oldnick = self.nickname
            newnick = params[0]
            self.nickname = newnick
            reserved_nick = self.matches_xline("Q")
            self.nickname = oldnick # restore the old nick temporarily so we can do the rest of the stuff we need to with the old nick
            if reserved_nick:
                self.sendMessage(irc.ERR_ERRONEUSNICKNAME, newnick, ":Invalid nickname: {}".format(reserved_nick))
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
                if not cdata.log.closed:
                    cdata.log.write("[{:02d}:{:02d}:{:02d}] {} is now known as {}\n".format(now().hour, now().minute, now().second, oldnick, newnick))
            for u in tomsg:
                self.ircd.users[u].sendMessage("NICK", to=newnick, prefix=oldprefix)
    
    def irc_USER(self, prefix, params):
        self.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
    
    def irc_OPER(self, prefix, params):
        if len(params) < 2:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters")
        elif self.ip not in self.ircd.oper_ips:
            self.sendMessage(irc.ERR_NOOPERHOST, ":No O-lines for your host")
        elif params[0] not in self.ircd.oper_logins or self.ircd.oper_logins[params[0]] != crypt(params[1],self.ircd.oper_logins[params[0]]):
            self.sendMessage(irc.ERR_PASSWDMISMATCH, ":Password incorrect")
        else:
            self.mode.modes["o"] = True
            self.sendMessage(irc.RPL_YOUREOPER, ":You are now an IRC operator")
    
    def irc_QUIT(self, prefix, params):
        if not self.nickname in self.ircd.users:
            return # Can't quit twice
        self.add_to_whowas()
        reason = params[0] if params else "Client exited"
        for c in self.channels.keys():
            self.quit(c,reason)
        del self.ircd.users[self.nickname]
        self.sendMessage("ERROR",":Closing Link: {} [{}]".format(self.prefix(), reason), to=None)
        self.socket.transport.loseConnection()

    def irc_JOIN(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters")
        elif params[0] == "0":
            for c in self.channels.keys():
                self.part(c, "Parting all channels")
        else:
            channels = params[0].split(",")
            keys = params[1].split(",") if len(params) > 1 else []
            for c in channels:
                if c in self.channels:
                    continue # don't join it twice
                k = keys.pop(0) if keys else None
                self.join(c,k)

    def irc_PART(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters")
        channels = params[0].split(",")
        reason = params[1] if len(params) > 1 else self.nickname
        for c in channels:
            self.part(c, reason)
    
    def irc_MODE(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters")
        elif params[0] in self.ircd.users:
            self.irc_MODE_user(params)
        elif params[0] in self.ircd.channels:
            self.irc_MODE_channel(params)
        else:
            self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")

    def irc_MODE_user(self, params):
        user = self.ircd.users[params[0]]
        if user.nickname != self.nickname and not self.mode.has("o"): # Not self and not an OPER
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, ":Can't {} for other users".format("view modes" if len(params) == 1 else "change mode"))
        else:
            if len(params) == 1:
                self.sendMessage(irc.RPL_UMODEIS, user.mode, to=user.nickname)
            else:
                response, bad, forbidden = user.mode.combine(params[1], params[2:], self.nickname)
                if response:
                    self.sendMessage("MODE", response, to=user.nickname, prefix=self.prefix())
                    if user.nickname != self.nickname: # Also send the mode change to the user if an oper is changing it
                        user.sendMessage("MODE", response, prefix=self.prefix())
                for mode in bad:
                    self.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, mode, ":is unknown mode char to me", to=user.nickname)
                for mode in forbidden:
                    self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission Denied - Only operators may set user mode {}".format(mode), to=user.nickname)

    def irc_MODE_channel(self, params):
        if len(params) == 1:
            self.irc_MODE_channel_show(params)
        elif len(params) == 2 and ("b" in params[1] or "e" in params[1] or "I" in params[1]):
            self.irc_MODE_channel_bans(params)
        elif self.hasAccess(params[0], "h") or self.mode.has("o"):
            self.irc_MODE_channel_change(params)
        else:
            self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, params[0], ":You must have channel halfop access or above to set channel modes")

    def irc_MODE_channel_show(self, params):
        cdata = self.ircd.channels[params[0]]
        self.sendMessage(irc.RPL_CHANNELMODEIS, cdata.name, "+{!s}".format(cdata.mode))
        self.sendMessage(irc.RPL_CREATIONTIME, cdata.name, str(epoch(cdata.created)))
    
    def irc_MODE_channel_change(self, params):
        cdata = self.ircd.channels[params.pop(0)]
        modes, bad, forbidden = cdata.mode.combine(params[0], params[1:], self.nickname)
        for mode in bad:
            self.sendMessage(irc.ERR_UNKNOWNMODE, mode, ":is unknown mode char to me")
        for mode in forbidden:
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - only operators may set mode {}".format(mode))
        if modes:
            if not cdata.log.closed:
                cdata.log.write("[{:02d}:{:02d}:{:02d}] {} set modes {}\n".format(now().hour, now().minute, now().second, self.nickname, modes))
            for u in cdata.users.itervalues():
                u.sendMessage("MODE", modes, to=cdata.name, prefix=self.prefix())

    def irc_MODE_channel_bans(self, params):
        cdata = self.ircd.channels[params[0]]
        if "b" in params[1]:
            if cdata.mode.has("b"):
                for banmask, settertime in cdata.mode.get("b").iteritems():
                    self.sendMessage(irc.RPL_BANLIST, cdata.name, banmask, settertime[0], str(epoch(settertime[1])))
            self.sendMessage(irc.RPL_ENDOFBANLIST, cdata.name, ":End of channel ban list")
        if "e" in params[1]:
            if cdata.mode.has("e"):
                for exceptmask, settertime in cdata.mode.get("e").iteritems():
                    self.sendMessage(irc.RPL_EXCEPTLIST, cdata.name, exceptmask, settertime[0], str(epoch(settertime[1])))
            self.sendMessage(irc.RPL_ENDOFEXCEPTLIST, cdata.name, ":End of channel exception list")
        if "I" in params[1]:
            if cdata.mode.has("I"):
                for invexmask, settertime in cdata.mode.get("I").iteritems():
                    self.sendMessage(irc.RPL_INVITELIST, cdata.name, invexmask, settertime[0], str(epoch(settertime[1])))
            self.sendMessage(irc.RPL_ENDOFINVITELIST, cdata.name, ":End of channel invite exception list")

    def irc_TOPIC(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "TOPIC", ":Not enough parameters")
            return
        if params[0] not in self.ircd.channels:
            self.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return
        cdata = self.ircd.channels[params[0]]
        if len(params) == 1:
            if cdata.topic["message"] is None:
                self.sendMessage(irc.RPL_NOTOPIC, cdata.name, "No topic is set")
            else:
                self.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic["message"]))
                self.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topic["author"], str(epoch(cdata.topic["created"])))
        else:
            if self.nickname not in cdata.users:
                self.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not in that channel")
            elif not cdata.mode.has("t") or self.hasAccess(params[0],"h") or self.mode.has("o"):
                # If the channel is +t and the user has a rank that is halfop or higher, allow the topic change
                cdata.topic["message"] = params[1]
                cdata.topic["author"] = self.nickname
                cdata.topic["created"] = now()
                for u in cdata.users.itervalues():
                    u.sendMessage("TOPIC", ":{}".format(cdata.topic["message"]), to=cdata.name, prefix=self.prefix())
                if not cdata.log.closed:
                    cdata.log.write("[{:02d}:{:02d}:{:02d}] {} changed the topic to {}\n".format(now().hour, now().minute, now().second, self.nickname, params[1]))
            else:
                self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You do not have access to change the topic on this channel")
    
    def irc_KICK(self, prefix, params):
        if not params or len(params) < 2:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KICK", ":Not enough parameters")
            return
        if len(params) == 2:
            params.append(self.nickname) # default reason used on many IRCds
        if params[0] not in self.ircd.channels:
            self.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return
        if params[1] not in self.ircd.users:
            self.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick")
            return
        cdata = self.ircd.channels[params[0]]
        udata = self.ircd.users[params[1]]
        if self.nickname not in cdata.users:
            self.sendMessage(irc.ERR_NOTONCHANNEL, cdata["names"], ":You're not on that channel!")
            return
        if udata.nickname not in cdata.users:
            self.sendMessage(irc.ERR_USERNOTINCHANNEL, udata.nickname, cdata.name, ":They are not on that channel")
            return
        if not self.hasAccess(params[0], "h") or (not self.accessLevel(params[0]) > udata.accessLevel(params[0]) and not self.mode.has("o")):
            self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You must be a channel half-operator")
            return
        for u in cdata.users.itervalues():
            u.sendMessage("KICK", udata.nickname, ":{}".format(params[2]), to=cdata.name, prefix=self.prefix())
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
                    self.sendMessage(irc.RPL_WHOREPLY, "*", u.username, u.hostname, self.ircd.server_name, u.nickname, "{}{}".format("G" if u.mode.has("a") else "H", "*" if u.mode.has("o") else ""), ":0 {}".format(u.realname))
            self.sendMessage(irc.RPL_ENDOFWHO, self.nickname, "*", ":End of /WHO list.")
        else:
            filters = ""
            if len(params) >= 2:
                filters = params[1]
            if params[0] in self.ircd.channels:
                cdata = self.ircd.channels[params[0]]
                in_channel = cdata.name in self.channels # cache this value instead of searching self.channels every iteration
                for user in cdata.users.itervalues():
                    if (in_channel or not user.mode.has("i")) and ("o" not in filters or user.mode.has("o")):
                        self.sendMessage(irc.RPL_WHOREPLY, cdata.name, user.username, user.hostname, self.ircd.server_name, user.nickname, "{}{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else "", self.ircd.prefix_symbols[self.ircd.prefix_order[len(self.ircd.prefix_order) - user.accessLevel(cdata.name)]] if user.accessLevel(cdata.name) > 0 else ""), ":0 {}".format(user.realname))
                self.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
            elif params[0][0] in self.ircd.channel_prefixes:
                self.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.")
            else:
                for user in self.ircd.users.itervalues():
                    if not user.mode.has("i") and (fnmatch.fnmatch(irc_lower(user.nickname), irc_lower(params[0])) or fnmatch.fnmatch(irc_lower(user.hostname), irc_lower(params[0]))):
                        self.sendMessage(irc.RPL_WHOREPLY, params[0], user.username, user.hostname, self.ircd.server_name, user.nickname, "{}{}".format("G" if user.mode.has("a") else "H", "*" if user.mode.has("o") else ""), ":0 {}".format(user.realname))
                self.sendMessage(irc.RPL_ENDOFWHO, params[0], ":End of /WHO list.")
                # params[0] is used here for the target so that the original glob pattern is returned
    
    def irc_WHOIS(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
            return
        users = params[0].split(",")
        for uname in users:
            if uname not in self.ircd.users:
                self.sendMessage(irc.ERR_NOSUCHNICK, uname, ":No such nick/channel")
                self.sendMessage(irc.RPL_ENDOFWHOIS, "*", ":End of /WHOIS list.")
                continue
            udata = self.ircd.users[uname]
            self.sendMessage(irc.RPL_WHOISUSER, udata.nickname, udata.username, udata.ip if self.mode.has("o") else udata.hostname, "*", ":{}".format(udata.realname))
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
                    self.sendMessage(irc.RPL_WHOISCHANNELS, udata.nickname, ":{}".format(" ".join(chanlist)))
            self.sendMessage(irc.RPL_WHOISSERVER, udata.nickname, self.ircd.server_name, ":{}".format(self.ircd.network_name))
            if udata.mode.has("a"):
                self.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.mode.get("a")))
            if udata.mode.has("o"):
                self.sendMessage(irc.RPL_WHOISOPERATOR, udata.nickname, ":is an IRC operator")
            if udata.account:
                self.sendMessage(irc.RPL_WHOISACCOUNT, udata.nickname, udata.account, ":is logged in as")
            if udata.socket.secure:
                self.sendMessage(irc.RPL_WHOISSECURE, udata.nickname, ":is using a secure connection")
            self.sendMessage(irc.RPL_WHOISIDLE, udata.nickname, str(epoch(now()) - epoch(udata.lastactivity)), str(epoch(udata.signon)), ":seconds idle, signon time")
            self.sendMessage(irc.RPL_ENDOFWHOIS, udata.nickname, ":End of /WHOIS list.")
    
    def irc_WHOWAS(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NONICKNAMEGIVEN, self.nickname, ":No nickname given")
            return
        users = params[0].split(",")
        for uname in users:
            if uname not in self.ircd.whowas:
                self.sendMessage(irc.ERR_WASNOSUCHNICK, self.nickname, uname, ":No such nick")
                self.sendMessage(irc.RPL_ENDOFWHOWAS, self.nickname, "*", ":End of /WHOWAS list.")
                continue
            history = self.ircd.whowas[uname]
            for u in history:
                self.sendMessage(irc.RPL_WHOISUSER, u["nickname"], u["username"], u["ip"] if self.mode.has("o") else u["hostname"], "*", ":{}".format(u["realname"]))
                self.sendMessage(irc.RPL_WHOISSERVER, u["nickname"], self.ircd.server_name, ":{}".format(u["time"]))
            self.sendMessage(irc.RPL_ENDOFWHOWAS, uname, ":End of /WHOWAS list.")
            
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
        for c in channels:
            self.report_names(c)
    
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
                self.sendMessage(irc.RPL_LIST, cdata.name, str(len(cdata.users)), ":{}".format(cdata.topic["message"]))
            elif cdata.mode.has("p") and not cdata.mode.has("s"):
                self.sendMessage(irc.RPL_LIST, "*", str(len(cdata.users)), ":")
        self.sendMessage(irc.RPL_LISTEND, ":End of /LIST")
    
    def irc_INVITE(self, prefix, params):
        if len(params) < 2:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "INVITE", ":Not enough parameters")
        elif params[0] not in self.ircd.users:
            self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
        elif params[1] not in self.ircd.channels:
            self.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick/channel")
        
        udata = self.ircd.users[params[0]]
        cdata = self.ircd.channels[params[1]]
        if cdata.name in udata.channels:
            self.sendMessage(irc.ERR_USERONCHANNEL, udata.nickname, cdata.name, ":is already on channel")
        elif cdata.name not in self.channels:
            self.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not on that channel")
        elif cdata.mode.has("i") and not self.hasAccess(cdata.name, "h"):
            self.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You're not channel operator")
        elif udata.mode.has("a"):
            self.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.mode.get("a")))
        else:
            self.sendMessage(irc.RPL_INVITING, udata.nickname, to=cdata.name)
            udata.sendMessage("INVITE", cdata.name, to=udata.nickname, prefix=self.prefix())
            udata.invites.append(cdata.name)
    
    def irc_MOTD(self, prefix, params):
        self.send_motd()
    
    def irc_AWAY(self, prefix, params):
        if not params:
            if self.mode.has("a"):
                del self.mode.modes["a"]
            self.sendMessage(irc.RPL_UNAWAY, ":You are no longer marked as being away")
        else:
            self.mode.modes["a"] = params[0]
            self.sendMessage(irc.RPL_NOWAWAY, ":You have been marked as being away")
    
    def irc_KILL(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission Denied - You do not have the required operator privileges")
            return
        if not params or len(params) < 2:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KILL", ":Not enough parameters.")
        elif params[0] not in self.ircd.users:
            self.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick")
        else:
            udata = self.ircd.users[params[0]]
            udata.sendMessage("KILL", ":{} ({})".format(self.nickname, params[1]))
            udata.irc_QUIT(None, ["Killed by {} ({})".format(self.nickname, params[1])])
    
    def irc_GLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "GLINE", ":Not enough parameters")
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("G", banmask)
        else:
            banmask = irc_lower(params[0])
            if banmask in self.ircd.users: # banmask is a nick of an active user; user@host isn't a valid nick so no worries there
                user = self.ircd.users[banmask]
                banmask = irc_lower("{}@{}".format(user.username, user.hostname))
            elif "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("G", banmask, parse_duration(params[1]), params[2])
    
    def irc_KLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "KLINE", ":Not enough parameters")
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("K", banmask)
        else:
            banmask = irc_lower(params[0])
            if banmask in self.ircd.users: # banmask is a nick of an active user; user@host isn't a valid nick so no worries there
                user = self.ircd.users[banmask]
                banmask = irc_lower("{}@{}".format(user.username, user.hostname))
            elif "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("K", banmask, parse_duration(params[1]), params[2])
    
    def irc_ZLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
            return
        if params[0][0] == "-":
            self.remove_xline("Z", params[0][1:])
        else:
            banip = params[0]
            if banip in self.ircd.users:
                banip = self.ircd.users[banip].ip
            self.add_xline("Z", banip, parse_duration(params[1]), params[2])
    
    def irc_ELINE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ELINE", ":Not enough parameters")
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("E", params[0][1:])
        else:
            banmask = irc_lower(params[0])
            if banmask in self.ircd.users:
                user = self.ircd.users[banmask]
                banmask = irc_lower("{}@{}".format(user.username, user.hostname))
            elif "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("E", banmask, parse_duration(params[1]), params[2])
    
    def irc_QLINE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
            return
        if params[0][0] == "-":
            self.remove_xline("Q", params[0][1:])
        else:
            nickmask = irc_lower(params[0])
            if VALID_USERNAME.match(nickmask.replace("*","").replace("?","a")):
                self.add_xline("Q", nickmask, parse_duration(params[1]), params[2])
            else:
                self.sendMessage("NOTICE", ":*** Could not set Q:Line: invalid nickmask")
    
    def irc_SHUN(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not params or (params[0][0] != "-" and len(params) < 3):
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
            return
        if params[0][0] == "-":
            banmask = irc_lower(params[0][1:])
            if "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.remove_xline("SHUN", banmask)
        else:
            banmask = irc_lower(params[0])
            if banmask in self.ircd.users:
                user = self.ircd.users[banmask]
                banmask = irc_lower("{}@{}".format(user.username, user.hostname))
            elif "@" not in banmask:
                banmask = "*@{}".format(banmask)
            self.add_xline("SHUN", banmask, parse_duration(params[1]), params[2])
    
    def irc_VERSION(self, prefix, params):
        self.sendMessage(irc.RPL_VERSION, self.ircd.version, self.ircd.server_name, ":txircd")
    
    def irc_TIME(self, prefix, params):
        self.sendMessage(irc.RPL_TIME, self.ircd.server_name, ":{}".format(now()))
    
    def irc_ADMIN(self, prefix, params):
        self.sendMessage(irc.RPL_ADMINME, self.ircd.server_name, ":Administrative info")
        self.sendMessage(irc.RPL_ADMINLOC1, ":{}".format(self.ircd.admin_info_server))
        self.sendMessage(irc.RPL_ADMINLOC2, ":{}".format(self.ircd.admin_info_organization))
        self.sendMessage(irc.RPL_ADMINEMAIL, ":{}".format(self.ircd.admin_info_person))
    
    def irc_INFO(self, prefix, params):
        self.sendMessage(irc.RPL_INFO, ":txircd")
        self.sendMessage(irc.RPL_ENDOFINFO, ":End of INFO list")
    
    def irc_REHASH(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        self.ircd.rehash()
        self.sendMessage(irc.RPL_REHASHING, self.ircd.config, ":Rehashing")
    
    def irc_DIE(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not self.ircd.oper_allow_die:
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Server does not allow use of DIE command")
            return
        reactor.stop()
    
    def irc_RESTART(self, prefix, params):
        if not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return
        if not self.ircd.oper_allow_die:
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Server does not allow use of RESTART command")
            return
        def restart():
            os.execl(sys.executable, sys.executable, *sys.argv)
        reactor.addSystemEventTrigger("after", "shutdown", restart)
        reactor.stop()
    
    def irc_USERHOST(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "USERHOST", ":Not enough parameters")
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
        self.sendMessage(irc.RPL_USERHOST, ":{}".format(" ".join(reply_list)))
    
    def irc_ISON(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "ISON", ":Not enough parameters")
            return
        reply = []
        for user in params:
            if user in self.ircd.users:
                reply.append(self.ircd.users[user].nickname)
        self.sendMessage(irc.RPL_ISON, ":{}".format(" ".join(reply)))
    
    def irc_STATS(self, prefix, params):
        if not params:
            self.sendMessage(irc.ERR_NEEDMOREPARAMS, "STATS", ":Not enough parameters")
            return
        if params[0][0] not in self.ircd.server_stats_public and not self.mode.has("o"):
            self.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Stats {} requires oper privileges".format(params[0][0]))
            return
        statsmethod = getattr(self, "stats_{}".format(params[0][0]), None)
        if statsmethod is not None:
            statsmethod()
        self.sendMessage(irc.RPL_ENDOFSTATS, params[0][0], ":End of /STATS report")
    
    def irc_unknown(self, prefix, command, params):
        self.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command")
        log.msg("--- Not Implemented Yet: {} {} {}".format(prefix, command, " ".join(params)))
