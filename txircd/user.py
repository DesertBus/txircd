from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols import irc
from twisted.internet.defer import Deferred
from txircd.channel import IRCChannel
from txircd.server import ChangeNick, JoinChannel, LeaveChannel, RegisterUser, RemoveUser, SetHost, SetIdent, SetMetadata, SetMode, SetName
from txircd.utils import irc_lower, now, epoch, CaseInsensitiveDictionary, chunk_message, IPV4_MAPPED_ADDR
import socket, uuid

class IRCUser(object):
    def __init__(self, parent):
        # Mask the IP
        ip = parent.transport.getPeer().host
        mapped = IPV4_MAPPED_ADDR.match(ip)
        if mapped:
            ip = mapped.group(1)
        try:
            hostname = socket.gethostbyaddr(ip)[0]
        except:
            hostname = ip
        
        # Set attributes
        self.ircd = parent.factory
        self.socket = parent
        self.uuid = str(uuid.uuid1())
        while self.uuid in self.ircd.userid:
            self.uuid = str(uuid.uuid1())
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name: # only operate on servers with the attribute
                server.ignoreUsers.discard(self.uuid)
        self.password = None
        self.nickname = None
        self.username = None
        self.realname = None
        self.hostname = hostname
        self.ip = ip
        self.realhost = hostname
        self.server = parent.factory.name
        self.signon = now()
        self.nicktime = now()
        self.lastactivity = now()
        self.lastpong = now()
        self.mode = {}
        self.disconnected = Deferred()
        self.registered = 2
        self.metadata = { # split into metadata key namespaces, see http://ircv3.atheme.org/specification/metadata-3.2
            "server": {},
            "user": {},
            "client": {},
            "ext": {},
            "private": {}
        }
        self.cache = {}
        self.ircd.userid[self.uuid] = self
    
    def register(self):
        if self.nickname in self.ircd.users:
            return
        tryagain = []
        for action in self.ircd.actions["register"]:
            outCode = action(self)
            if outCode == "again":
                tryagain.append(action)
            elif not outCode:
                log.msg("The new user {} was prevented from connecting by a module.".format(self.nickname))
                return self.disconnect(None)
        for action in tryagain:
            if not action(self):
                log.msg("The new user {} was prevented from connecting by a module.".format(self.nickname))
                return self.disconnect(None)
        
        # Add self to user list
        self.ircd.users[self.nickname] = self
        
        # Send notification of connection to other servers
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name:
                server.callRemote(RegisterUser, uuid=self.uuid, nick=self.nickname, ident=self.username, host=self.hostname, realhost=self.realhost, gecos=self.realname, ip=self.ip, server=self.server, secure=self.socket.secure, signon=epoch(self.signon), nickts=epoch(self.nicktime))
        
        # Send all those lovely join messages
        chanmodelist = "".join("".join(["".join(modedict.keys()) for modedict in self.ircd.channel_modes]) + "".join(self.ircd.prefixes.keys()))
        usermodelist = "".join(["".join(modedict.keys()) for modedict in self.ircd.user_modes])
        self.sendMessage(irc.RPL_WELCOME, ":Welcome to the Internet Relay Network {}".format(self.prefix()))
        self.sendMessage(irc.RPL_YOURHOST, ":Your host is {}, running version {}".format(self.ircd.servconfig["server_network_name"], self.ircd.version))
        self.sendMessage(irc.RPL_CREATED, ":This server was created {}".format(self.ircd.created))
        self.sendMessage(irc.RPL_MYINFO, self.ircd.servconfig["server_network_name"], self.ircd.version, usermodelist, chanmodelist) # usermodes & channel modes
        self.send_isupport()
        self.send_lusers()
        self.send_motd()
        for action in self.ircd.actions["welcome"]:
            action(self)
    
    def send_isupport(self):
        isupport = []
        for key, value in self.ircd.isupport.iteritems():
            if value is None:
                isupport.append(key)
            else:
                isupport.append("{}={}".format(key, value))
        prevar_len = len(" ".join([self.ircd.name, irc.RPL_ISUPPORT, self.nickname])) + 31 # including ":are supported by this server"
        thisline = []
        while isupport:
            if len(" ".join(thisline)) + len(isupport[0]) + prevar_len > 509:
                self.sendMessage(irc.RPL_ISUPPORT, " ".join(thisline), ":are supported by this server")
                thisline = []
            thisline.append(isupport.pop(0))
        if thisline:
            self.sendMessage(irc.RPL_ISUPPORT, " ".join(thisline), ":are supported by this server")
    
    def disconnect(self, reason, sourceServer = None):
        if self.registered == 0 and self.uuid in self.ircd.userid:
            del self.ircd.userid[self.uuid]
            for modfunc in self.ircd.actions["quit"]:
                modfunc(self, reason)
            if self.nickname:
                quitdest = set()
                exitChannels = []
                for channel in self.ircd.channels.itervalues():
                    if self in channel.users:
                        exitChannels.append(channel)
                for channel in exitChannels:
                    del channel.users[self] # remove channel user entry
                    if not channel.users:
                        for modfunc in self.ircd.actions["chandestroy"]:
                            modfunc(channel)
                        del self.ircd.channels[channel.name] # destroy the empty channel
                    for u in channel.users.iterkeys():
                        quitdest.add(u)
                udata = self.ircd.users[self.nickname]
                if udata == self:
                    del self.ircd.users[self.nickname]
                for user in quitdest:
                    user.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(RemoveUser, user=self.uuid, reason=reason)
        self.sendMessage("ERROR", ":Closing Link: {}@{} [{}]".format(self.username if self.username else "unknown", self.hostname, reason), to=None, prefix=None)
        self.socket.transport.loseConnection()
    
    def checkData(self, data):
        if data > self.ircd.servconfig["client_max_data"] and "o" not in self.mode:
            log.msg("Killing user '{}' for flooding".format(self.nickname))
            self.disconnect("Killed for flooding")
    
    def connectionLost(self, reason):
        self.disconnect("Connection Lost")
        self.disconnected.callback(None)
    
    def handleCommand(self, command, prefix, params):
        if command in self.ircd.commands:
            cmd = self.ircd.commands[command]
            cmd.updateActivity(self)
            data = cmd.processParams(self, params)
            if not data:
                return
            permData = self.commandPermission(command, data)
            if permData:
                cmd.onUse(self, permData)
                for action in self.ircd.actions["commandextra"]:
                    action(command, data)
        else:
            present_error = True
            for modfunc in self.ircd.actions["commandunknown"]:
                if modfunc(self, command, params):
                    present_error = False
            if present_error:
                self.sendMessage(irc.ERR_UNKNOWNCOMMAND, command, ":Unknown command")
    
    def commandPermission(self, command, data):
        tryagain = set()
        for modfunc in self.ircd.actions["commandpermission"]:
            permData = modfunc(self, command, data)
            if permData == "again":
                tryagain.add(modfunc)
            else:
                data = permData
                if "force" in data and data["force"]:
                    return data
                if not data:
                    return {}
        for modeset in self.ircd.channel_modes:
            for implementation in modeset.itervalues():
                permData = implementation.checkPermission(self, command, data)
                if permData == "again":
                    tryagain.add(implementation.checkPermission)
                else:
                    data = permData
                    if "force" in data and data["force"]:
                        return data
                    if not data:
                        return {}
        for modeset in self.ircd.user_modes:
            for implementation in modeset.itervalues():
                permData = implementation.checkPermission(self, command, data)
                if permData == "again":
                    tryagain.add(implementation.checkPermission)
                else:
                    data = permData
                    if "force" in data and data["force"]:
                        return data
                    if not data:
                        return {}
        for modfunc in tryagain:
            data = modfunc(self, command, data)
            if "force" in data and data["force"]:
                return data
            if not data:
                return {}
        return data
    
    def sendMessage(self, command, *parameter_list, **kw):
        if "prefix" not in kw:
            kw["prefix"] = self.ircd.name
        if not kw["prefix"]:
            del kw["prefix"]
        if "to" not in kw:
            kw["to"] = self.nickname if self.nickname else "*"
        if kw["to"]:
            arglist = [command, kw["to"]] + list(parameter_list)
        else:
            arglist = [command] + list(parameter_list)
        self.socket.sendMessage(*arglist, **kw)
    
    def setMetadata(self, namespace, key, value, sourceServer = None):
        if not value:
            self.delMetadata(namespace, key, sourceServer)
            return
        oldValue = self.metadata[namespace][key] if key in self.metadata[namespace] else ""
        self.metadata[namespace][key] = value
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, value)
        if self.registered == 0:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(SetMetadata, target=self.uuid, targetts=epoch(self.signon), namespace=namespace, key=key, value=value)
    
    def delMetadata(self, namespace, key, sourceServer = None):
        oldValue = self.metadata[namespace][key]
        del self.metadata[namespace][key]
        for modfunc in self.ircd.actions["metadataupdate"]:
            modfunc(self, namespace, key, oldValue, "")
        if self.registered == 0:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(SetMetadata, target=self.uuid, targetts=epoch(self.signon), namespace=namespace, key=key, value="")
    
    #=====================
    #== Utility Methods ==
    #=====================
    def prefix(self):
        return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
    
    def hasAccess(self, channel, level):
        if self not in channel.users or level not in self.ircd.prefixes:
            return None
        status = channel.users[self]
        if not status:
            return False
        return self.ircd.prefixes[status[0]][1] >= self.ircd.prefixes[level][1]
    
    def setUsername(self, newUsername, sourceServer = None):
        self.username = str(newUsername)
        if self.registered == 0:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(SetIdent, user=self.uuid, ident=newUsername)
    
    def setHostname(self, newHostname, sourceServer = None):
        self.hostname = str(newHostname)
        if self.registered == 0:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(SetHost, user=self.uuid, host=newHostname)
    
    def setRealname(self, newRealname, sourceServer = None):
        self.realname = str(newRealname)
        if self.registered == 0:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name and server.name != sourceServer:
                    server.callRemote(SetName, user=self.uuid, gecos=newRealname)
    
    def setMode(self, user, modes, params, displayPrefix = None):
        adding = True
        currentParam = 0
        modeDisplay = []
        for mode in modes:
            if mode == "+":
                adding = True
            elif mode == "-":
                adding = False
            else:
                if mode not in self.ircd.user_mode_type:
                    if user:
                        user.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, mode, ":is unknown mode char to me")
                    continue
                modetype = self.ircd.user_mode_type[mode]
                if modetype == 1 or (adding and modetype == 2) or (modetype == 0 and len(params) > currentParam):
                    if len(params) <= currentParam:
                        continue # mode must have parameter, but one wasn't provided
                    param = params[currentParam]
                    currentParam += 1
                    if " " in param:
                        param = param[:param.find(" ")]
                else:
                    param = None
                if not (modetype == 0 and param is None): # ignore these checks for list modes so that they can be listed
                    if not adding and mode not in self.mode:
                        continue # cannot unset a mode that's not set
                    if user:
                        if adding:
                            allowed, param = self.ircd.user_modes[modetype][mode].checkSet(user, self, param)
                            if not allowed:
                                continue
                        else:
                            allowed, param = self.ircd.user_modes[modetype][mode].checkUnset(user, self, param)
                            if not allowed:
                                continue
                if modetype == 0:
                    if not param and user:
                        self.ircd.user_modes[modetype][mode].showParam(user, self)
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
            if user:
                self.sendMessage("MODE", modeLine, prefix=user.prefix())
                lineSource = user.prefix()
            elif displayPrefix:
                self.sendMessage("MODE", modeLine, prefix=displayPrefix)
                lineSource = displayPrefix
            else: # display from this server
                self.sendMessage("MODE", modeLine)
                lineSource = self.ircd.name
            
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name:
                    server.callRemote(SetMode, target=self.uuid, targetts=epoch(self.signon), source=lineSource, modestring="".join(modestring), params=showParams)
            for action in self.ircd.actions["mode"]:
                action(self, lineSource, modeLine, modeDisplay)
            return modeLine
        return ""
    
    def modeString(self, user):
        modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
        params = []
        for mode, param in self.mode.iteritems():
            modetype = self.ircd.user_mode_type[mode]
            if modetype > 0:
                modes.append(mode)
                if param:
                    if user:
                        params.append(self.ircd.user_modes[modetype][mode].showParam(user, self, param))
                    else:
                        params.append(param)
        return ("+{} {}".format("".join(modes), " ".join(params)) if params else "+{}".format("".join(modes)))
    
    def send_motd(self):
        if "server_motd" in self.ircd.servconfig and self.ircd.servconfig["server_motd"]:
            chunks = chunk_message(self.ircd.servconfig["server_motd"], self.ircd.servconfig["server_motd_line_length"])
            self.sendMessage(irc.RPL_MOTDSTART, ":- {} Message of the day - ".format(self.ircd.servconfig["server_network_name"]))
            for chunk in chunks:
                line = ":- {{:{!s}}} -".format(self.ircd.servconfig["server_motd_line_length"]).format(chunk) # Dynamically inject the line length as a width argument for the line
                self.sendMessage(irc.RPL_MOTD, line)
            self.sendMessage(irc.RPL_ENDOFMOTD, ":End of MOTD command")
        else:
            self.sendMessage(irc.ERR_NOMOTD, ":MOTD File is missing")
    
    def send_lusers(self):
        userCount = 0
        invisibleCount = 0
        serverCount = 0
        networkServerCount = len(self.ircd.servers) + 1 # this server is also a server
        operCount = 0
        localCount = 0
        globalCount = 0
        for user in self.ircd.users.itervalues():
            globalCount += 1
            if user.server == self.ircd.name:
                localCount += 1
            if "i" in user.mode:
                invisibleCount += 1
            else:
                userCount += 1
            if "o" in user.mode:
                operCount += 1
        for server in self.ircd.servers.itervalues():
            if self.ircd.name == server.nearHop:
                serverCount += 1
        if localCount > self.ircd.usercount["localmax"]:
            self.ircd.usercount["localmax"] = localCount
        if globalCount > self.ircd.usercount["globalmax"]:
            self.ircd.usercount["globalmax"] = globalCount
        self.sendMessage(irc.RPL_LUSERCLIENT, ":There are {} users and {} invisible on {} server{}.".format(userCount, invisibleCount, networkServerCount, "" if networkServerCount == 1 else "s"))
        self.sendMessage(irc.RPL_LUSEROP, str(operCount), ":operator(s) online")
        self.sendMessage(irc.RPL_LUSERCHANNELS, str(len(self.ircd.channels)), ":channels formed")
        self.sendMessage(irc.RPL_LUSERME, ":I have {} clients and {} servers".format(localCount, serverCount))
        self.sendMessage(irc.RPL_LOCALUSERS, ":Current Local Users: {}  Max: {}".format(localCount, self.ircd.usercount["localmax"]))
        self.sendMessage(irc.RPL_GLOBALUSERS, ":Current Global Users: {}  Max: {}".format(globalCount, self.ircd.usercount["globalmax"]))
    
    def report_names(self, channel):
        userlist = []
        for user, ranks in channel.users.iteritems():
            representation = (self.ircd.prefixes[ranks[0]][0] + user.nickname) if ranks else user.nickname
            newRepresentation = self.listname(channel, user, representation)
            if newRepresentation:
                userlist.append(newRepresentation)
        # Copy of irc.IRC.names
        prefixLength = len(self.ircd.name) + len(irc.RPL_NAMREPLY) + len(channel.name) + len(self.nickname) + 10 # 10 characters for CRLF, =, : and spaces
        namesLength = 512 - prefixLength # May get messed up with unicode
        lines = chunk_message(" ".join(userlist), namesLength)
        for l in lines:
            self.sendMessage(irc.RPL_NAMREPLY, "=", channel.name, ":{}".format(l))
        self.sendMessage(irc.RPL_ENDOFNAMES, channel.name, ":End of /NAMES list")
    
    def listname(self, channel, listingUser, representation):
        for modfunc in self.ircd.actions["nameslistentry"]:
            representation = modfunc(self, channel, listingUser, representation)
            if not representation:
                return representation
        return representation
    
    def join(self, channel):
        if self in channel.users:
            return
        status = ""
        for server in self.ircd.servers.itervalues(): # Send this first before the chancreate hook screws up everything
            if server.nearHop == self.ircd.name:
                server.callRemote(JoinChannel, channel=channel.name, chants=epoch(channel.created), user=self.uuid)
        if channel.name not in self.ircd.channels:
            self.ircd.channels[channel.name] = channel
            for modfunc in self.ircd.actions["chancreate"]:
                modfunc(channel)
            status = self.ircd.servconfig["channel_default_status"]
        channel.users[self] = status
        joinShowUsers = channel.users.keys()
        tryagain = []
        for modfunc in self.ircd.actions["joinmessage"]:
            result = modfunc(channel, self, joinShowUsers)
            if result == "again":
                tryagain.append(modfunc)
            else:
                joinShowUsers = result
        for modfunc in tryagain:
            joinShowUsers = modfunc(channel, self, joinShowUsers)
        for u in joinShowUsers:
            u.sendMessage("JOIN", to=channel.name, prefix=self.prefix())
        if channel.topic:
            self.sendMessage(irc.RPL_TOPIC, channel.name, ":{}".format(channel.topic))
            self.sendMessage(irc.RPL_TOPICWHOTIME, channel.name, channel.topicSetter, str(epoch(channel.topicTime)))
        else:
            self.sendMessage(irc.RPL_NOTOPIC, channel.name, ":No topic is set")
        self.report_names(channel)
        if status:
            for server in self.ircd.servers.itervalues():
                if server.nearHop == self.ircd.name:
                    server.callRemote(SetMode, target=channel.name, targetts=epoch(channel.created), source=self.ircd.name, modestring="+{}".format(status), params=[self.nickname for i in range(len(status))])
        for modfunc in self.ircd.actions["join"]:
            modfunc(self, channel)
    
    def leave(self, channel, sourceServer = None):
        del channel.users[self] # remove channel user entry
        if not channel.users:
            for modfunc in self.ircd.actions["chandestroy"]:
                modfunc(channel)
            del self.ircd.channels[channel.name] # destroy the empty channel
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name and server.name != sourceServer:
                server.callRemote(LeaveChannel, channel=channel.name, user=self.uuid)
    
    def nick(self, newNick):
        newNick = str(newNick)
        if newNick in self.ircd.users:
            return
        del self.ircd.users[self.nickname]
        self.ircd.users[newNick] = self
        notify = set()
        notify.add(self)
        for cdata in self.ircd.channels.itervalues():
            if self in cdata.users:
                for cuser in cdata.users.iterkeys():
                    notify.add(cuser)
        prefix = self.prefix()
        for u in notify:
            u.sendMessage("NICK", to=newNick, prefix=prefix)
        oldNick = self.nickname
        self.nickname = newNick
        self.nicktime = now()
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name:
                server.callRemote(ChangeNick, user=self.uuid, newnick=self.nickname)
        for modfunc in self.ircd.actions["nick"]:
            modfunc(self, oldNick)