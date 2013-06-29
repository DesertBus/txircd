from twisted.internet.defer import Deferred
from twisted.internet.protocol import Factory, ClientFactory
from twisted.protocols.amp import AMP, Command, Integer, String, Boolean, AmpList, ListOf, IncompatibleVersions
from txircd.channel import IRCChannel
from txircd.utils import CaseInsensitiveDictionary, epoch, now
from datetime import datetime

protocol_version = 200 # Protocol version 0.2.0
# The protocol version should be incremented with changes of the protocol
# Breaking changes should be avoided except for major version upgrades or when it's otherwise unavoidable

# Keep a list of versions the current protocol is compatible with
# This list must include the current protocol version
compatible_versions = [ 200 ]

class RemoteUser(object):
    class RemoteSocket(object):
        class RemoteTransport(object):
            def loseConnection(self):
                pass
        
        def __init__(self, secure):
            self.transport = self.RemoteTransport()
            self.secure = secure
    
    def __init__(self, ircd, nick, ident, host, gecos, ip, server, secure, signonTime, nickTime):
        self.ircd = ircd
        self.socket = self.RemoteSocket(secure)
        self.password = None
        self.nickname = nick
        self.username = ident
        self.realname = gecos
        self.hostname = host
        self.ip = ip
        self.server = server
        self.signon = signonTime
        self.nicktime = nickTime
        self.lastactivity = now()
        self.disconnected = Deferred()
        self.disconnected.callback(None)
        self.mode = {}
        self.channels = CaseInsensitiveDictionary()
        self.registered = 0
        self.metadata = { # split into metadata key namespaces, see http://ircv3.atheme.org/specification/metadata-3.2
            "server": {},
            "user": {},
            "client": {},
            "ext": {},
            "private": {}
        }
        self.cache = {}
        self.cmd_extra = False # used by the command handler to determine whether the extras hook was called during processing
    
    def register(self):
        pass
    
    def send_isupport(self):
        pass # TODO?
    
    def disconnect(self, reason):
        quitdest = set()
        leavingChannels = self.channels.keys()
        for channel in leavingChannels:
            cdata = self.ircd.channels[channel]
            del self.channels[cdata.name]
            cdata.users.remove(self)
            if not cdata.users:
                for modfunc in self.ircd.actions["chandestroy"]:
                    modfunc(channel)
                del self.ircd.channels[cdata.name]
            for u in cdata.users:
                quitdest.add(u)
        del self.ircd.users[self.nickname]
        for user in quitdest:
            user.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
    
    def sendMessage(self, command, *parameter_list, **kw):
        pass # TODO
    
    def setMetadata(self, namespace, key, value):
        pass # TODO
    
    def delMetadata(self, namespace, key):
        pass # TODO
    
    def prefix(self):
        return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
    
    def hasAccess(self, channel, level):
        if channel not in self.channels or level not in self.ircd.prefixes:
            return None
        status = self.status(channel)
        if not status:
            return False
        return self.ircd.prefixes[status[0]][1] >= self.ircd.prefixes[level][1]
    
    def status(self, channel):
        if channel not in self.channels:
            return ""
        return self.channels[channel]["status"]
    
    def modeString(self, user):
        modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
        params = []
        for mode, param in self.mode.iteritems():
            modetype = self.ircd.user_mode_type[mode]
            if modetype > 0:
                modes.append(mode)
                if param:
                    params.append(self.ircd.user_modes[modetype][mode].showParam(user, self, param))
        return ("+{} {}".format("".join(modes), " ".join(params)) if params else "+{}".format("".join(modes)))
    
    def send_motd(self):
        pass # TODO?
    
    def send_lusers(self):
        pass # TODO?
    
    def report_names(self, channel):
        pass # TODO?
    
    def join(self, channel):
        pass # TODO
    
    def leave(self, channel):
        pass # TODO
    
    def nick(self, newNick):
        pass # TODO

class RemoteServer(object):
    def __init__(self, ircd, name, desc, nearestServer, hopCount):
        self.ircd = ircd
        self.name = name
        self.description = desc
        self.nearHop = nearestServer
        self.burstComplete = True
        self.remoteServers = set()
        self.hopCount = hopCount
    
    def callRemote(self, command, *args):
        server = self
        while server.nearHop != self.ircd.name and server.nearHop in self.ircd.servers:
            server = self.ircd.servers[server.nearHop]
        if server.name in self.ircd.servers:
            server.callRemote(command, *args) # If the parameters are such that they indicate the target properly, this will be forwarded to the proper server.


# ERRORS
class HandshakeAlreadyComplete:
    pass

class ServerAlreadyConnected(Exception):
    pass

class ServerMismatchedIP(Exception):
    pass

class ServerPasswordIncorrect(Exception):
    pass

class ServerNoLink(Exception):
    pass

class ModuleMismatch(Exception):
    pass

class BurstIncomplete(Exception):
    pass

class AlreadyBursted(Exception):
    pass

class NotYetBursted(Exception):
    pass

class ServerNotConnected(Exception):
    pass

class RemoteDataInconsistent(Exception):
    pass

# TODO: errbacks to handle all of these


# COMMANDS
class IntroduceServer(Command):
    arguments = [
        ("name", String()), # server name
        ("password", String()), # server password specified in configuration
        ("description", String()), # server description
        ("version", Integer()), # protocol version
        ("commonmodules", ListOf(String()))
    ]
    errors = {
        HandshakeAlreadyComplete: "HANDSHAKE_ALREADY_COMPLETE"
    }
    fatalErrors = {
        ServerAlreadyConnected: "SERVER_ALREADY_CONNECTED",
        ServerMismatchedIP: "SERVER_MISMATCHED_IP",
        ServerPasswordIncorrect: "SERVER_PASS_INCORRECT",
        ServerNoLink: "SERVER_NO_LINK",
        ModuleMismatch: "MODULE_MISMATCH"
    }
    requiresAnswer = False

class BurstData(Command):
    arguments = [
        ("users", AmpList([
            ("nickname", String()),
            ("ident", String()),
            ("host", String()),
            ("gecos", String()),
            ("ip", String()),
            ("server", String()),
            ("secure", Boolean()),
            ("mode", ListOf(String())),
            ("channels", AmpList([("name", String()), ("status", String())])),
            ("signon", Integer()),
            ("ts", Integer())
        ])),
        ("channels", AmpList([
            ("name", String()),
            ("topic", String()),
            ("topicsetter", String()),
            ("topicts", Integer()),
            ("mode", ListOf(String())),
            ("users", ListOf(String())),
            ("ts", Integer())
        ])),
        ("servers", AmpList([
            ("name", String()),
            ("description", String()),
            ("hopcount", Integer()),
            ("nearhop", String()),
            ("remoteservers", ListOf(String()))
        ]))
    ]
    errors = {
        AlreadyBursted: "ALREADY_BURSTED"
    }
    requiresAnswer = False

class AddNewServer(Command):
    arguments = [
        ("name", String()),
        ("description", String()),
        ("hopcount", Integer()),
        ("nearhop", String()),
        ("linkedservers", AmpList([
            ("name", String()),
            ("description", String()),
            ("hopcount", Integer()),
            ("nearhop", String()),
            ("remoteservers", ListOf(String()))
        ])),
        ("users", AmpList([
            ("nickname", String()),
            ("ident", String()),
            ("host", String()),
            ("gecos", String()),
            ("ip", String()),
            ("server", String()),
            ("secure", Boolean()),
            ("mode", ListOf(String())),
            ("channels", AmpList([("name", String()), ("status", String())])),
            ("signon", Integer()),
            ("ts", Integer())
        ])),
        ("channels", AmpList([
            ("name", String()),
            ("topic", String()),
            ("topicsetter", String()),
            ("topicts", Integer()),
            ("mode", ListOf(String())),
            ("users", ListOf(String())),
            ("ts", Integer())
        ]))
    ]
    errors = {
        NotYetBursted: "NOT_YET_BURSTED"
    }
    fatalErrors = {
        ServerAlreadyConnected: "SERVER_ALREADY_CONNECTED", # If this error is present, the servers are already desynced, so have them fully disconnect and try again
        RemoteDataInconsistent: "REMOTE_DATA_IS_INCONSISTENT" # This is a more serious desync of data; disconnect this serious of a desync
    }
    requiresAnswer = False

class DisconnectServer(Command):
    arguments = [
        ("name", String())
    ]
    errors = {
        NotYetBursted: "NOT_YET_BURSTED"
    }
    fatalErrors = {
        ServerNotConnected: "NO_SUCH_SERVER"
    }
    requiresAnswer = False


class ServerProtocol(AMP):
    def __init__(self, ircd):
        self.ircd = ircd
        self.burstComplete = False
        self.burstStatus = []
        self.name = None
        self.description = None
        self.remoteServers = set()
        self.localOrigin = False
        self.nearHop = self.ircd.name
        self.nearRemoteLink = self.ircd.name
        self.hopCount = 1
    
    def serverHandshake(self, name, password, description, version, commonmodules):
        if "handshake-recv" in self.burstStatus:
            raise HandshakeAlreadyComplete ("The server handshake has already been completed between these servers.")
        self.burstStatus.append("handshake-recv")
        if version not in compatible_versions:
            raise IncompatibleVersions ("Protocol version {} is not compatible with this version".format(version))
        commonModDiff = set(commonmodules) ^ self.ircd.common_modules
        if commonModDiff:
            raise ModuleMismatch ("Common modules are not matched between servers: {}".format(", ".join(commonModDiff)))
        if name not in self.ircd.servconfig["serverlinks"]:
            raise ServerNoLink ("There is no link data in the configuration file for the server trying to link.")
        if name in self.ircd.servers or self.ircd.name == name:
            raise ServerAlreadyConnected ("The connecting server is already connected to this network.")
        linkData = self.ircd.servconfig["serverlinks"][name]
        ip = self.transport.getPeer().host
        if "ip" not in linkData or ip != linkData["ip"]:
            raise ServerMismatchedIP ("The IP address for this server does not match the one in the configuration.")
        if "incoming_password" not in linkData or password != linkData["incoming_password"]:
            raise ServerPasswordIncorrect ("The password provided by the server does not match the one in the configuration.")
        if "handshake-send" not in self.burstStatus:
            self.callRemote(IntroduceServer, name=self.ircd.name, password=linkData["outgoing_password"], description=self.ircd.servconfig["server_description"], version=protocol_version, commonmodules=self.ircd.common_modules)
            self.burstStatus.append("handshake-send")
        else:
            self.sendBurstData()
        self.name = name
        self.description = description
        return {}
    IntroduceServer.responder(serverHandshake)
    
    def burstData(self, users, channels, servers):
        if "handshake-send" not in self.burstStatus or "handshake-recv" not in self.burstStatus:
            raise BurstIncomplete ("The handshake was not completed before attempting to burst data.")
        if "burst-recv" in self.burstStatus:
            raise AlreadyBursted ("Data has already been bursted to this server.")
        self.sendBurstData() # Respond by sending our own burst data if we haven't yet
        incomingChannels = []
        propUsers = []
        propChannels = []
        for chan in channels:
            newChannel = IRCChannel(self.ircd, chan["name"])
            newChannel.created = datetime.utcfromtimestamp(chan["ts"])
            newChannel.topic = chan["topic"]
            newChannel.topicSetter = chan["topicsetter"]
            newChannel.topicTime = datetime.utcfromtimestamp(chan["topicts"])
            newChannel.cache["mergingusers"] = chan["users"]
            for mode in chan["mode"]:
                modetype = self.ircd.channel_mode_type[mode[0]]
                if modetype == 0:
                    if mode[0] not in newChannel.mode:
                        newChannel.mode[mode[0]] = []
                    newChannel.mode[mode[0]].append(mode[1:])
                elif modetype == 3:
                    newChannel.mode[mode[0]] = None
                else:
                    newChannel.mode[mode[0]] = mode[1:]
            incomingChannels.append([newChannel, chan])
        for udata in users:
            if udata["nickname"] in self.ircd.users: # a user with the same nickname is already connected
                ourudata = self.ircd.users[udata["nickname"]]
                ourts = epoch(ourudata.nicktime)
                if ourts == udata["ts"]: # older user wins; if same, they both die
                    ourudata.disconnect("Nickname collision")
                    for channel in incomingChannels:
                        if udata["nickname"] in channel[0].cache["mergingusers"]:
                            channel[0].cache["mergingusers"].remove(udata["nickname"])
                    continue
                elif ourts > udata["ts"]:
                    ourudata.disconnect("Nickname collision")
                else:
                    for channel in incomingChannels:
                        if udata["nickname"] in channel[0].cache["mergingusers"]:
                            channel[0].cache["mergingusers"].remove(udata["nickname"])
                    continue # skip adding the remote user since they'll die on the remote server
            newUser = RemoteUser(self.ircd, udata["nickname"], udata["ident"], udata["host"], udata["gecos"], udata["ip"], udata["server"], udata["secure"], datetime.utcfromtimestamp(udata["signon"]), datetime.utcfromtimestamp(udata["ts"]))
            for mode in udata["mode"]:
                modetype = self.ircd.user_mode_type[mode[0]]
                if modetype == 0:
                    if mode[0] not in newUser.mode:
                        newUser.mode[mode[0]] = []
                    newUser[mode[0]].append(mode[1:])
                elif modetype == 3:
                    newUser.mode[mode[0]] = None
                else:
                    newUser.mode[mode[0]] = mode[1:]
            for chan in udata["channels"]:
                newUser.channels[chan["name"]] = { "status": chan["status"] } # This will get fixed in the channel merging to immediately follow
            self.ircd.users[udata["nickname"]] = newUser
            propUsers.append(udata)
        for chandata in incomingChannels:
            channel, cdata = chandata
            for user in channel.cache["mergingusers"]:
                channel.users.add(self.ircd.users[user])
            del channel.cache["mergingusers"]
            if channel.name not in self.ircd.channels:
                self.ircd.channels[channel.name] = channel # simply add the channel to our list
                propChannels.append(cdata)
            else:
                mergeChanData = self.ircd.channels[channel.name]
                if channel.created == mergeChanData.created: # ... matching timestamps? Time to resolve lots of conflicts
                    # topics: if identical contents and setter but different timestamps, keep older timestamp
                    # if different topics, keep newer topic
                    if channel.topic == mergeChanData.topic and channel.topicSetter == mergeChanData.topicSetter:
                        if channel.topicTime < mergeChanData.topicTime:
                            mergeChanData.topicTime = channel.topicTime # If the topics are identical, go with the lower timestamp
                    else:
                        if mergeChanData.topicTime < channel.topicTime or (mergeChanData.topicTime == channel.topicTime and self.localOrigin):
                            mergeChanData.setTopic(channel.topic, channel.topicSetter)
                            mergeChanData.topicTime = channel.topicTime
                            for user in mergeChanData.users:
                                user.sendMessage("TOPIC", ":{}".format(channel.topic), to=mergeChanData.name)
                    cdata["topic"] = mergeChanData.topic
                    cdata["topicsetter"] = mergeChanData.topicSetter
                    cdata["topicts"] = epoch(mergeChanData.topicTime)
                    # modes: merge modes together
                    # break parameter ties on normal parameter modes by giving the winner to the server being connected to
                    modeDisplay = []
                    paramDisplay = []
                    for mode, param in channel.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            for item in param:
                                if item not in mergeChanData.mode[mode]:
                                    mergeChanData.mode[mode].append(item)
                                    modeDisplay.append(mode)
                                    paramDisplay.append(param)
                        elif modetype == 3:
                            if mode not in mergeChanData.mode:
                                mergeChanData.mode[mode] = None
                                modeDisplay.append(mode)
                        else:
                            if mode not in mergeChanData.mode:
                                mergeChanData.mode[mode] = param
                                modeDisplay.append(mode)
                                paramDisplay.append(param)
                            elif self.localOrigin:
                                mergeChanData.mode[mode] = param
                                modeDisplay.append(mode)
                                paramDisplay.append(param)
                    if modeDisplay:
                        if paramDisplay:
                            for user in mergeChanData.users:
                                user.sendMessage("MODE", "+{} {}".format("".join(modeDisplay), " ".join(paramDisplay)), to=mergeChanData.name)
                        else:
                            for user in mergeChanData.users:
                                user.sendMessage("MODE", "+{}".format("".join(modeDisplay)), to=mergeChanData.name)
                    # channel lists are already fine, just notify users
                    for user in channel.users:
                        self.justSendJoin(user, mergeChanData)
                        if user.channels[mergeChanData.name]["status"]:
                            modestr = "+{} {}".format(user.channels[mergeChanData.name]["status"], " ".join([user.nickname for i in range(len(user.channels[mergeChanData.name]["status"]))]))
                            for u in mergeChanData.users:
                                u.sendMessage("MODE", modestr, to=mergeChanData.name)
                    for user in channel.users: # Run this as a separate loop so that remote users don't get repeat join messages for users already in that channel
                        mergeChanData.users.add(user)
                    # reserialize modes for other servers
                    cdata["modes"] = []
                    for mode, param in mergeChanData.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            for item in param:
                                cdata["modes"].append("{}{}".format(mode, item))
                        elif modetype == 3:
                            cdata["modes"].append(mode)
                        else:
                            cdata["modes"].append("{}{}".format(mode, param))
                    # also reserialize users
                    cdata["users"] = []
                    for u in mergeChanData.users:
                        cdata["users"].append(u.nickname)
                    propChannels.append(cdata)
                elif channel.created < mergeChanData.created: # theirs is older, so discard any changes ours made
                    mergeChanData.created = channel.created # Set the proper timestamp
                    # Topic: If the contents and setter are the same, adopt the remote timestamp; otherwise, adopt the
                    # remote topic and alert users of the change
                    if channel.topic == mergeChanData.topic and channel.topicSetter == mergeChanData.topicSetter:
                        mergeChanData.topicTime = channel.topicTime
                    else:
                        mergeChanData.setTopic(channel.topic, channel.topicSetter)
                        mergeChanData.topicTime = channel.topicTime
                        for user in mergeChanData.users:
                            user.sendMessage("TOPIC", ":{}".format(channel.topic), to=mergeChanData.name)
                    cdata["topic"] = mergeChanData.topic
                    cdata["topicsetter"] = mergeChanData.topicSetter
                    cdata["topicts"] = epoch(mergeChanData.topicTime)
                    # Modes: Take modes of remote side; keep track of mode changes to alert our users
                    modeDisplay = []
                    removeModes = []
                    for mode, param in mergeChanData.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            listData = param
                            for item in listData:
                                if mode not in channel.mode or item not in channel.mode[mode]:
                                    param.remove(item)
                                    modeDisplay.append([False, mode, param])
                                if mode not in channel.mode:
                                    removeModes.append(mode)
                        elif modetype == 3:
                            if mode not in channel.mode:
                                removeModes.append(mode)
                                modeDisplay.append([False, mode, None])
                        else:
                            if mode not in channel.mode:
                                removeModes.append(mode)
                                modeDisplay.append([False, mode, param])
                    for mode in removeModes:
                        del mergeChanData.mode[mode]
                    for mode, param in channel.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            if mode not in mergeChanData.mode:
                                mergeChanData.mode[mode] = []
                            if param not in mergeChanData.mode[mode]:
                                mergeChanData.mode[mode].append(param)
                                modeDisplay.append([True, mode, param])
                        else:
                            if mode not in mergeChanData.mode or mergeChanData.mode[mode] != param:
                                mergeChanData.mode[mode] = param
                                modeDisplay.append([True, mode, param])
                    # Users (local): remove statuses, send mode change notice
                    for user in mergeChanData.users:
                        statuses = user.channels[mergeChanData.name]["status"]
                        user.channels[mergeChanData.name]["status"] = ""
                        for status in statuses:
                            modeDisplay.append([False, status, user.nickname])
                    # Users (remote): show join and statuses of new users
                    for user in channel.users:
                        statuses = user.channels[channel.name]["status"]
                        for status in statuses:
                            modeDisplay.append([True, status, user.nickname])
                        self.justSendJoin(user, mergeChanData)
                    for user in channel.users: # Run as a second loop so remote users don't get another JOIN message about users already in that channel
                        mergeChanData.users.add(user)
                    # Send all the modes we should be sending
                    if modeDisplay:
                        modeStr = []
                        params = []
                        adding = None
                        for mode in modeDisplay:
                            if mode[0] and adding is not True:
                                modeStr.append("+")
                                adding = True
                            elif not mode[0] and adding is not False:
                                modeStr.append("-")
                                adding = False
                            modeStr.append(mode[1])
                            if mode[2]:
                                params.append(mode[2])
                        if params:
                            for user in mergeChanData.users:
                                if user.nickname in self.ircd.localusers: # Don't send this to remote users who will get it anyway once the data propagates
                                    user.sendMessage("MODE", "{} {}".format("".join(modeStr), " ".join(params)), to=mergeChanData.name)
                        else:
                            for user in mergeChanData.users:
                                if user.nickname in self.ircd.localusers:
                                    user.sendMessage("MODE", "".join(modeStr), to=mergeChanData.name)
                    # reserialize modes for other servers
                    cdata["mode"] = []
                    for mode, param in mergeChanData.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            for item in param:
                                cdata["mode"].append("{}{}".format(mode, item))
                        elif modetype == 3:
                            cdata["mode"].append(mode)
                        else:
                            cdata["mode"].append("{}{}".format(mode, param))
                    # Also reserialize users
                    cdata["users"] = []
                    for u in mergeChanData.users:
                        cdata["users"].append(u.nickname)
                    propChannels.append(cdata)
                else: # ours is older, so discard any changes theirs made
                    # topic: keep ours; ignore theirs
                    # modes: keep ours; ignore theirs
                    # users (local): keep same
                    # users (remote): remove status, add to channel
                    for user in channel.users:
                        user.channels[channel.name]["status"] = ""
                        self.justSendJoin(user, mergeChanData)
                    for user in channel.users: # Use a second loop so remote users don't get extra JOIN messages about users already in that channel
                        mergeChanData.users.add(user)
                    cdata["topic"] = mergeChanData.topic
                    cdata["topicsetter"] = mergeChanData.topicSetter
                    cdata["topicts"] = epoch(mergeChanData.topicTime)
                    cdata["mode"] = []
                    for mode, param in mergeChanData.mode.iteritems():
                        modetype = self.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            for item in param:
                                cdata["mode"].append("{}{}".format(mode, item))
                        elif modetype == 3:
                            cdata["mode"].append(mode)
                        else:
                            cdata["mode"].append("{}{}".format(mode, param))
                    cdata["users"] = []
                    for u in mergeChanData.users:
                        cdata["users"].append(u.nickname)
                    propChannels.append(cdata)
        self.burstStatus.append("burst-recv")
        self.burstComplete = True
        
        for server in self.ircd.servers.itervalues():
            server.callRemote(AddNewServer, name=self.name, description=self.description, hopcount=self.hopCount, nearhop=self.ircd.name, linkedservers=servers, users=propUsers, channels=propChannels)
        
        self.ircd.servers[self.name] = self
        for server in servers:
            newServer = RemoteServer(self.ircd, server["name"], server["description"], server["nearhop"], server["hopcount"] + 1)
            for servname in server["remoteservers"]:
                newServer.remoteServers.add(servname)
            self.ircd.servers[server["name"]] = newServer
            self.remoteServers.add(server["name"])
        for action in self.ircd.actions["netmerge"]:
            action()
        return {}
    BurstData.responder(burstData)
    
    def justSendJoin(self, user, channel):
        joinShowUsers = set(channel.users) # copy the channel.users set to prevent accidental modification of the users list
        tryagain = []
        for modfunc in self.ircd.actions["joinmessage"]:
            result = modfunc(channel, user, joinShowUsers)
            if result == "again":
                tryagain.append(modfunc)
            else:
                joinShowUsers = result
        for modfunc in tryagain:
            joinShowUsers = modfunc(channel, user, joinShowUsers)
        for u in joinShowUsers:
            u.sendMessage("JOIN", to=channel.name, prefix=user.prefix())
    
    def sendBurstData(self):
        if "burst-send" in self.burstStatus:
            return
        userList = []
        for u in self.ircd.users.itervalues():
            modes = []
            for mode, param in u.mode.iteritems():
                if self.ircd.user_mode_type[mode] == 0:
                    for item in param:
                        modes.append("{}{}".format(mode, item))
                elif param is None:
                    modes.append(mode)
                else:
                    modes.append("{}{}".format(mode, param))
            channels = []
            for name, data in u.channels.iteritems():
                status = data["status"]
                channels.append({
                    "name": name,
                    "status": status
                })
            userList.append({
                "nickname": u.nickname,
                "ident": u.username,
                "host": u.hostname,
                "gecos": u.realname,
                "ip": u.ip,
                "server": u.server,
                "secure": u.socket.secure,
                "mode": modes,
                "channels": channels,
                "signon": epoch(u.signon),
                "ts": epoch(u.nicktime)
            })
        channelList = []
        for chan in self.ircd.channels.itervalues():
            modes = []
            for mode, param in chan.mode.iteritems():
                if self.ircd.channel_mode_type[mode] == 0:
                    for item in param:
                        modes.append("{}{}".format(mode, item))
                elif param is None:
                    modes.append(mode)
                else:
                    modes.append("{}{}".format(mode, param))
            users = []
            for u in chan.users:
                users.append(u.nickname)
            channelList.append({
                "name": chan.name,
                "topic": chan.topic,
                "topicsetter": chan.topicSetter,
                "topicts": epoch(chan.topicTime),
                "mode": modes,
                "users": users,
                "ts": epoch(chan.created)
            })
        serverList = []
        for server in self.ircd.servers.itervalues():
            serverList.append({
                "name": server.name,
                "description": server.description,
                "hopcount": server.hopCount,
                "nearhop": server.nearHop,
                "remoteservers": server.remoteServers
            })
        self.callRemote(BurstData, users=userList, channels=channelList, servers=serverList)
        self.burstStatus.append("burst-send")
    
    def newServer(self, name, description, hopcount, nearhop, linkedservers, users, channels):
        if not self.burstComplete:
            raise NotYetBursted ("The remote server has not yet bursted.")
        # check for server-related desyncs
        if name in self.ircd.servers:
            raise ServerAlreadyConnected ("The server trying to connect to the network is already connected to the network.")
        if nearhop not in self.ircd.servers:
            raise RemoteDataInconsistent ("The connecting server on the network is not part of the network.")
        for server in linkedservers:
            if server["name"] in self.ircd.servers:
                raise ServerAlreadyConnected ("A server connected to the remote network is already connected to this network.")
        # Since user and channel data should have been filtered/processed on burst by the receiving server before being broadcast,
        # raise an error if any user data is inconsistent
        # Nickname collision kills must have occurred before notification of the new server, so any problem here indicates that a
        # desyncing of user data has occurred
        for u in users:
            if u["nickname"] in self.ircd.users:
                raise RemoteDataInconsistent ("A user on a connecting remote server matches a user here.")
        
        # Set up the new server(s)
        newServer = RemoteServer(self.ircd, name, description, nearhop, hopcount + 1)
        nearHop = self.ircd.servers[nearhop]
        nearHop.remoteServers.add(name)
        for server in self.ircd.servers.itervalues():
            if nearhop in server.remoteServers:
                server.remoteServers.add(name)
                for addingServer in linkedservers:
                    server.remoteServers.add(addingServer["name"])
        self.ircd.servers[name] = newServer
        # Add linked servers
        remoteLinkedServers = []
        for servinfo in linkedservers:
            farServer = RemoteServer(self.ircd, servinfo["name"], servinfo["description"], servinfo["nearhop"], servinfo["hopcount"] + 1)
            for server in servinfo["remoteservers"]:
                farServer.remoteServers.append(server)
            remoteLinkedServers.append(servinfo["name"])
            newServer.remoteServers.append(farServer.name)
            self.ircd.servers[farServer.name] = farServer
        nextServer = newServer.nearHop
        while nextServer != self.ircd.name:
            nextServerPtr = self.ircd.servers[nextServer]
            for servname in remoteLinkedServers:
                nextServerPtr.remoteServers.append(servname)
            nextServer = nextServerPtr.nearHop
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name and server != self:
                # The server is connected to this server but is NOT this server link
                # so that it goes to each server once and does not get sent back where it came from
                server.callRemote(AddNewServer, name=name, description=description, hopcount=hopcount+1, nearhop=nearhop, linkedservers=linkedservers, users=users, channels=channels)
        if not users and not channels:
            return {}
        
        # Add new users to list
        for u in users:
            newUser = RemoteUser(self.ircd, u["nickname"], u["ident"], u["host"], u["gecos"], u["ip"], u["server"], u["secure"], datetime.utcfromtimestamp(u["signon"]), datetime.utcfromtimestamp(u["ts"]))
            for chan in u["channels"]:
                newUser.channels[chan["name"]] = {"status": chan["status"]}
            for modedata in u["mode"]:
                mode = modedata[0]
                param = modedata[1:]
                modetype = self.ircd.user_mode_type[mode]
                if modetype == 0:
                    if mode not in newUser.mode:
                        newUser.mode[mode] = []
                    newUser.mode[mode].append(param)
                elif modetype == 3:
                    newUser.mode[mode] = None
                else:
                    newuser.mode[mode] = param
            self.ircd.users[newUser.nickname] = newUser
        # Add new channels and merge channel data
        for c in channels:
            cdata = IRCChannel(self.ircd, c["name"])
            cdata.topic = c["topic"]
            cdata.topicSetter = c["topicsetter"]
            cdata.topicTime = datetime.utcfromtimestamp(c["topicts"])
            for modedata in c["mode"]:
                mode = modedata[0]
                param = modedata[1:]
                modetype = self.ircd.channel_mode_type[mode]
                if modetype == 0:
                    if mode not in cdata.mode:
                        cdata.mode[mode] = []
                    cdata.mode[mode].append(param)
                elif modetype == 3:
                    cdata.mode[mode] = None
                else:
                    cdata.mode[mode] = param
            cdata.created = datetime.utcfromtimestamp(c["ts"])
            for u in c["users"]:
                cdata.users.add(self.ircd.users[u])
            if cdata.name in self.ircd.channels:
                oldcdata = self.ircd.channels[cdata.name]
                if cdata.topic != oldcdata.topic:
                    for u in oldcdata.users:
                        if u.server == self.ircd.name: # local users only; remote users will get notified by their respective servers
                            u.sendMessage("TOPIC", ":{}".format(cdata.topic), to=cdata.name)
                modeDisplay = []
                for mode, param in oldcdata.mode.iteritems():
                    modetype = self.ircd.channel_mode_type[mode]
                    if mode not in cdata.mode:
                        if modetype == 0:
                            for item in param:
                                modeDisplay.append([False, mode, item])
                        else:
                            modeDisplay.append([False, mode, param])
                    elif modetype == 0:
                        for item in param:
                            if item not in cdata.mode[mode]:
                                modeDisplay.append([False, mode, item])
                for mode, param in cdata.mode.iteritems():
                    modetype = self.ircd.channel_mode_type[mode]
                    if mode not in oldcdata.mode:
                        if modetype == 0:
                            for item in param:
                                modeDisplay.append([True, mode, item])
                        else:
                            modeDisplay.append([True, mode, param])
                    elif modetype == 0:
                        for item in param:
                            if item not in oldcdata.mode[mode]:
                                modeDisplay.append([True, mode, item])
                    else:
                        if param != oldcdata.mode[mode]:
                            modeDisplay.append([True, mode, param])
                if cdata.created < oldcdata.created:
                    for user in oldcdata.users:
                        chanstatus = user.channels[oldcdata.name]["status"]
                        if chanstatus:
                            user.channels[oldcdata.name]["status"] = ""
                            for mode in chanstatus:
                                modeDisplay.append([False, mode, user.nickname])
                for u in cdata.users:
                    if u not in oldcdata.users:
                        self.justSendJoin(u, oldcdata)
                        if cdata.created <= oldcdata.created:
                            chanstatus = u.channels[cdata.name]["status"]
                            for mode in chanstatus:
                                modeDisplay.append([True, mode, u.nickname])
                        else:
                            u.channels[cdata.name]["status"] = ""
                if modeDisplay:
                    adding = None
                    modeString = []
                    params = []
                    for mode in modeDisplay:
                        if mode[0] and adding is not True:
                            adding = True
                            modeString.append("+")
                        elif not mode[0] and adding is not False:
                            adding = False
                            modeString.append("-")
                        modeString.append(mode[1])
                        if mode[2] is not None:
                            params.append(mode[2])
                    modeLine = "{} {}".format("".join(modeString), " ".join(params))
                    for u in oldcdata.users:
                        if u.server == self.ircd.name:
                            u.sendMessage("MODE", modeLine, to=cdata.name)
            self.ircd.channels[cdata.name] = cdata
        return {}
    AddNewServer.responder(newServer)
    
    def splitServer(self, name):
        if not self.burstComplete:
            raise NotYetBursted ("The initial burst has not yet occurred on this connection.")
        if name not in self.ircd.servers:
            raise ServerNotConnected ("The server splitting from the network was not connected to the network.")
        servinfo = self.ircd.servers[name]
        leavingServers = servinfo.remoteServers
        leavingServers.add(name)
        userList = self.ircd.users.values()
        for user in userList:
            if user.server in leavingServers:
                user.disconnect("Server disconnected from network")
        for servname in leavingServers:
            del self.ircd.servers[servname]
        for server in self.ircd.servers.itervalues():
            for servname in leavingServers: # Remove splitting servers from all remoteServers sets
                server.remoteServers.discard(servname)
            if self.ircd.name == server.nearHop and server != self: # propagate to the rest of the servers
                server.callRemote(DisconnectServer, name=name)
        for action in self.ircd.actions["netsplit"]:
            action()
        return {}
    DisconnectServer.responder(splitServer)
    
    def connectionLost(self, reason):
        self.splitServer(self.name)
        AMP.connectionLost(self, reason)

# ClientServerFactory: Must be used as the factory when initiating a connection to a remote server
# This is to allow differentiating between a connection we initiated and a connection we received
# which is used to break ties in bursting when we absolutely cannot break the tie any other way.
# Failure to use this class as the factory when connecting to a remote server may lead to desyncs!
class ClientServerFactory(ClientFactory):
    protocol = ServerProtocol
    
    def __init__(self, ircd, remoteName):
        self.ircd = ircd
        self.name = remoteName
    
    def buildProtocol(self, addr):
        proto = ClientFactory.buildProtocol(self, addr)
        proto.name = self.name
        proto.localOrigin = True
        return proto

class ServerFactory(Factory):
    protocol = ServerProtocol
    
    def __init__(self, ircd):
        self.ircd = ircd
        self.ircd.server_factory = self
    
    def buildProtocol(self, addr):
        proto = self.protocol(self.ircd)
        proto.factory = self
        return proto