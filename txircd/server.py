from twisted.internet.protocol import Factory, ClientFactory
from twisted.protocols.amp import AMP, Command, Integer, String, AmpList, ListOf, IncompatibleVersions
from txircd.utils import CaseInsensitiveDictionary, epoch, now
from datetime import datetime

current_version = 200 # Protocol version 0.2.0
# The protocol version should be incremented with changes of the protocol
# Breaking changes should be avoided except for major version upgrades or when it's otherwise unavoidable

# Keep a list of versions the current protocol is compatible with
# This list must include the current protocol version
compatible_versions = [ 200 ]

class RemoteUser(object):
    class RemoteSocket(object):
        class RemoteTransport(object):
            def loseConnection():
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
        pass # TODO
    
    def connectionLost(self, reason):
        pass # TODO
    
    def handleCommand(self, command, prefix, params):
        pass # TODO
    
    def commandExtraHook(self, command, data):
        pass # TODO
    
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
    
    def certFP(self):
        pass # TODO
    
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
            ("ts": Integer())
        ]))
    ]
    errors = {
        AlreadyBursted: "ALREADY_BURSTED"
    }
    requiresAnswer = False


class ServerProtocol(AMP):
    def __init__(self, *args, **kwargs):
        self.ircd = self.factory.ircd
        self.burstComplete = False # TODO: set this to True somewhere
        self.burstStatus = []
        self.name = None
        self.remoteServers = []
        self.localOrigin = False
    
    def newServer(self, name, password, description, version, commonmodules):
        if "handshake-recv" in self.burstStatus:
            raise HandshakeAlreadyComplete ("The server handshake has already been completed between these servers.")
        self.burstStatus.append("handshake-recv")
        if version not in compatible_versions:
            raise IncompatibleVersions ("Protocol version {} is not compatible with this version".format(version))
        commonModDiff = commonmodules ^ self.ircd.common_modules
        if commonModDiff:
            raise ModuleMismatch ("Common modules are not matched between servers: {}".format(", ".join(commonModDiff)))
        if name not in self.ircd.servconfig["serverlinks"]:
            raise ServerNoLink ("There is no link data in the configuration file for the server trying to link.")
        if name in self.ircd.servers:
            raise ServerAlreadyConnected ("The connecting server is already connected to this network.")
        linkData = self.ircd.servconfig["serverlinks"][name]
        ip = self.transport.getPeer().host
        if "ip" not in linkData or ip != linkData["ip"]:
            raise ServerMismatchedIP ("The IP address for this server does not match the one in the configuration.")
        if "incoming_password" not in linkData or password != linkData["incoming_password"]:
            raise ServerPasswordIncorrect ("The password provided by the server does not match the one in the configuration.")
        if "handshake-send" not in self.burstStatus:
            self.callRemote(IntroduceServer, name=self.ircd.servconfig["server_name"], password=linkData["outgoing_password"], description=self.ircd.servconfig["server_description"], version=current_version, commonmodules=self.ircd.common_modules)
            self.burstStatus.append("handshake-send")
        else:
            self.sendUsers()
        self.name = name
        self.ircd.servers[name] = self
        return {}
    IntroduceServer.responder(newServer)
    
    def burstData(self, users, channels):
        if "handshake-send" not in self.burstStatus or "handshake-recv" not in self.burstStatus:
            raise BurstIncomplete ("The handshake was not completed before attempting to burst data.")
        if "burst-recv" in self.burstStatus:
            raise AlreadyBursted ("Data has already been bursted to this server.")
        incomingChannels = []
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
            incomingChannels.append(newChannel)
        for udata in users:
            if udata["nickname"] in self.ircd.users: # a user with the same nickname is already connected
                ourudata = self.ircd.users[udata["nickname"]]
                ourts = epoch(ourudata.nicktime)
                if ourts == udata["ts"]: # older user wins; if same, they both die
                    ourudata.disconnect("Nickname collision")
                    for channel in incomingChannels:
                        if udata["nickname"] in channel.cache["mergingusers"]:
                            channel.cache["mergingusers"].remove(udata["nickname"])
                    continue
                elif ourts > udata["ts"]:
                    ourudata.disconnect("Nickname collision")
                else:
                    for channel in incomingChannels:
                        if udata["nickname"] in channel.cache["mergingusers"]:
                            channel.cache["mergingusers"].remove(udata["nickname"])
                    continue # skip adding the remote user since they'll die on the remote server
            newUser = RemoteUser(self.ircd, udata["nickname"], udata["ident"], udata["host"], udata["gecos"], udata["ip"], self.name, udata["secure"], datetime.utcfromtimestamp(udata["signon"]), datetime.utcfromtimestamp(udata["ts"]))
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
        for channel in incomingChannels:
            for user in channel.cache["mergingusers"]:
                channel.users.add(self.ircd.users[user])
            del channel.cache["mergingusers"]
            if channel.name not in self.ircd.channels:
                self.ircd.channels[channel.name] = channel # simply add the channel to our list
            else:
                mergeChanData = self.ircd.channels[channel.name]
                if channel.created == mergeChanData.created: # ... matching timestamps? Time to resolve lots of conflicts
                    if channel.topicTime >= mergeChanData.topicTime:
                        # topics: if identical contents and setter but different timestamps, keep older timestamp
                        # if different topics, keep newer topic
                        if channel.topic == mergeChanData.topic and channel.topicSetter == mergeChanData.topicSetter:
                            channel.topicTime = mergeChanData.topicTime # If the topics are identical, go with the lower timestamp
                        else:
                            mergeChanData.setTopic(channel.topic, channel.topicSetter)
                            mergeChanData.topicTime = channel.topicTime
                            for user in mergeChanData.users:
                                user.sendMessage("TOPIC", ":{}".format(channel.topic), to=mergeChanData.name)
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
                    for user in channel.users: # Run this as a separate loop so that remote users don't get repeat join messages for users already in that channel
                        mergeChanData.users.add(user)
                elif channel.created < mergeChanData.created: # theirs is older, so discard any changes ours made
                    # Topic: If the contents and setter are the same, adopt the remote timestamp; otherwise, adopt the
                    # remote topic and alert users of the change
                    if channel.topic == mergeChanData.topic and channel.topicSetter == mergeChanData.topicSetter:
                        mergeChanData.topicTime = channel.topicTime
                    else:
                        mergeChanData.setTopic(channel.topic, channel.topicSetter)
                        mergeChanData.topicTime = channel.topicTime
                        for user in mergeChanData.users:
                            user.sendMessage("TOPIC", ":{}".format(channel.topic), to=mergeChanData.name)
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
                            mergeChanData.mode[mode].append(param)
                            modeDisplay.append([True, mode, param])
                        else:
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
                            elif not mode[0] and adding is not False:
                                modeStr.append("-")
                            modeStr.append(mode[1])
                            if mode[2]:
                                params.append(mode[2])
                        if params:
                            for user in mergeChanData.users:
                                user.sendMessage("MODE", "{} {}".format("".join(modeStr), " ".join(params)), to=mergeChanData.name)
                        else:
                            for user in mergeChanData.users:
                                user.sendMessage("MODE", "".join(modeStr), to=mergeChanData.name)
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
        return {}
    BurstData.responder(burstData)
    
    def justSendJoin(self, user, channel):
        joinShowUsers = set(mergeChanData.users) # copy the channel.users set to prevent accidental modification of the users list
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
            for name, data in u.channels:
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
        self.callRemote(burstData, users=userList, channels=channelList)
        self.burstStatus.append("burst-send")
    
    def connectionLost(self, reason):
        # TODO: remove all data from this server originating from remote
        if self.name:
            del self.ircd.servers[self.name]
        AMP.connectionLost(self, reason)

# ClientServerFactory: Must be used as the factory when initiating a connection to a remote server
# This is to allow differentiating between a connection we initiated and a connection we received
# which is used to break ties in bursting when we absolutely cannot break the tie any other way.
# Failure to use this class as the factory when connecting to a remote server may lead to desyncs!
class ClientServerFactory(ClientFactory):
    protocol = ServerProtocol
    
    def __init__(self, parent, ircd):
        self.parent = parent
        self.ircd = ircd
    
    def buildProtocol(self, addr):
        proto = ClientFactory.buildProtocol(self, addr)
        proto.localOrigin = True
        return proto

class ServerFactory(Factory):
    protocol = ServerProtocol
    
    def __init__(self, ircd):
        self.ircd = ircd
        self.client_factory = ClientServerFactory(self, ircd)
        self.ircd.server_factory = self