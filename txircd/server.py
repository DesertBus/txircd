from twisted.internet.protocol import Factory, ClientFactory
from twisted.protocols.amp import AMP, Command, Integer, String, Boolean, AmpList, ListOf, IncompatibleVersions
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
        self.firstHop = nearestServer
        self.burstComplete = True
        self.remoteServers = set()
        self.hopCount = hopCount
    
    def callRemote(self, command, *args):
        if self.firstHop in self.ircd.servers:
            self.ircd.servers[self.firstHop].callRemote(command, *args) # If the parameters are such that they indicate the target properly, this will be forwarded to the proper server.


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
        ]),
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
        ])))
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
    def __init__(self, *args, **kwargs):
        self.burstComplete = False
        self.burstStatus = []
        self.name = None
        self.description = None
        self.remoteServers = set()
        self.localOrigin = False
        self.firstHop = None
        self.hopCount = 0
    
    def connectionMade(self):
        if self.localOrigin:
            self.callRemote(IntroduceServer, name=self.ircd.name, password=self.ircd.servconfig["serverlinks"][name]["outgoing_password"], description=self.ircd.servconfig["server_description"], version=current_version, commonmodules=self.ircd.common_modules)
    
    def newServer(self, name, password, description, version, commonmodules):
        if "handshake-recv" in self.burstStatus:
            raise HandshakeAlreadyComplete ("The server handshake has already been completed between these servers.")
        self.burstStatus.append("handshake-recv")
        if version not in compatible_versions:
            raise IncompatibleVersions ("Protocol version {} is not compatible with this version".format(version))
        commonModDiff = set(commonmodules) ^ self.factory.ircd.common_modules
        if commonModDiff:
            raise ModuleMismatch ("Common modules are not matched between servers: {}".format(", ".join(commonModDiff)))
        if name not in self.factory.ircd.servconfig["serverlinks"]:
            raise ServerNoLink ("There is no link data in the configuration file for the server trying to link.")
        if name in self.factory.ircd.servers or self.factory.ircd.name == name:
            raise ServerAlreadyConnected ("The connecting server is already connected to this network.")
        linkData = self.factory.ircd.servconfig["serverlinks"][name]
        ip = self.transport.getPeer().host
        if "ip" not in linkData or ip != linkData["ip"]:
            raise ServerMismatchedIP ("The IP address for this server does not match the one in the configuration.")
        if "incoming_password" not in linkData or password != linkData["incoming_password"]:
            raise ServerPasswordIncorrect ("The password provided by the server does not match the one in the configuration.")
        if "handshake-send" not in self.burstStatus:
            self.callRemote(IntroduceServer, name=self.factory.ircd.name, password=linkData["outgoing_password"], description=self.factory.ircd.servconfig["server_description"], version=current_version, commonmodules=self.factory.ircd.common_modules)
            self.burstStatus.append("handshake-send")
        else:
            self.sendBurstData()
        self.name = name
        self.description = description
        self.firstHop = name
        return {}
    IntroduceServer.responder(newServer)
    
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
            newChannel = IRCChannel(self.factory.ircd, chan["name"])
            newChannel.created = datetime.utcfromtimestamp(chan["ts"])
            newChannel.topic = chan["topic"]
            newChannel.topicSetter = chan["topicsetter"]
            newChannel.topicTime = datetime.utcfromtimestamp(chan["topicts"])
            newChannel.cache["mergingusers"] = chan["users"]
            for mode in chan["mode"]:
                modetype = self.factory.ircd.channel_mode_type[mode[0]]
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
            if udata["nickname"] in self.factory.ircd.users: # a user with the same nickname is already connected
                ourudata = self.factory.ircd.users[udata["nickname"]]
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
            newUser = RemoteUser(self.factory.ircd, udata["nickname"], udata["ident"], udata["host"], udata["gecos"], udata["ip"], self.name, udata["secure"], datetime.utcfromtimestamp(udata["signon"]), datetime.utcfromtimestamp(udata["ts"]))
            for mode in udata["mode"]:
                modetype = self.factory.ircd.user_mode_type[mode[0]]
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
            self.factory.ircd.users[udata["nickname"]] = newUser
            propUsers.append(udata)
        for chandata in incomingChannels:
            channel, cdata = chandata
            for user in channel.cache["mergingusers"]:
                channel.users.add(self.factory.ircd.users[user])
            del channel.cache["mergingusers"]
            if channel.name not in self.factory.ircd.channels:
                self.factory.ircd.channels[channel.name] = channel # simply add the channel to our list
                propChannels.append(cdata)
            else:
                mergeChanData = self.factory.ircd.channels[channel.name]
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
                    else:
                        del cdata["topic"]
                        del cdata["topicsetter"]
                        del cdata["topicts"]
                    # modes: merge modes together
                    # break parameter ties on normal parameter modes by giving the winner to the server being connected to
                    modeDisplay = []
                    paramDisplay = []
                    for mode, param in channel.mode.iteritems():
                        modetype = self.factory.ircd.channel_mode_type[mode]
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
                            modestr = "+{} {}".format(user.channels[mergeChanData.name]["status"], " ".join([user.nickname for i in len(user.channels[mergeChanData.name]["status"])]))
                            for u in mergeChanData.users:
                                u.sendMessage("MODE", modestr, to=mergeChanData.name)
                    for user in channel.users: # Run this as a separate loop so that remote users don't get repeat join messages for users already in that channel
                        mergeChanData.users.add(user)
                    # reserialize modes for other servers
                    cdata["modes"] = []
                    for mode, param in channel.mode:
                        modetype = self.factory.ircd.channel_mode_type[mode]
                        if modetype == 0:
                            for item in param:
                                cdata["modes"].append("{}{}".format(mode, item))
                        elif modetype == 3:
                            cdata["modes"].append(mode)
                        else:
                            cdata["modes"].append("{}{}".format(mode, param))
                    propChannels.append(cdata)
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
                        modetype = self.factory.ircd.channel_mode_type[mode]
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
                        modetype = self.factory.ircd.channel_mode_type[mode]
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
                                if user.nickname in self.factory.ircd.localusers: # Don't send this to remote users who will get it anyway once the data propagates
                                    user.sendMessage("MODE", "{} {}".format("".join(modeStr), " ".join(params)), to=mergeChanData.name)
                        else:
                            for user in mergeChanData.users:
                                if user.nickname in self.factory.ircd.localusers:
                                    user.sendMessage("MODE", "".join(modeStr), to=mergeChanData.name)
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
        self.burstStatus.append("burst-recv")
        self.burstComplete = True
        
        for server in self.factory.ircd.servers.itervalues():
            server.callRemote(AddNewServer, name=self.name, description=self.description, hopcount=self.hopcount, nearhop=self.factory.ircd.name, linkedservers=servers, users=propUsers, channels=propChannels)
        
        self.factory.ircd.servers[self.name] = self
        for server in servers:
            newServer = RemoteServer(self.factory.ircd, server["name"], server["description"], server["nearhop"], server["hopcount"])
            for servname in server["remoteservers"]:
                newServer.remoteServers.add(servname)
            self.factory.ircd.servers[server["name"]] = newServer
        for action in self.factory.ircd.actions["netmerge"]:
            action()
        return {}
    BurstData.responder(burstData)
    
    def justSendJoin(self, user, channel):
        joinShowUsers = set(channel.users) # copy the channel.users set to prevent accidental modification of the users list
        tryagain = []
        for modfunc in self.factory.ircd.actions["joinmessage"]:
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
        for u in self.factory.ircd.users.itervalues():
            modes = []
            for mode, param in u.mode.iteritems():
                if self.factory.ircd.user_mode_type[mode] == 0:
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
        for chan in self.factory.ircd.channels.itervalues():
            modes = []
            for mode, param in chan.mode.iteritems():
                if self.factory.ircd.channel_mode_type[mode] == 0:
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
        for server in self.factory.ircd.servers.itervalues():
            serverList.append({
                "name": server.name,
                "description": server.desc
            })
        self.callRemote(burstData, users=userList, channels=channelList, servers=serverList)
        self.burstStatus.append("burst-send")
    
    def newServer(self, name, description, hopcount, nearhop, linkedservers, users, channels):
        if not self.burstComplete:
            raise NotYetBursted ("The remote server has not yet bursted.")
        # check for server-related desyncs
        if name in self.factory.ircd.servers:
            raise ServerAlreadyConnected ("The server trying to connect to the network is already connected to the network.")
        if nearhop not in self.factory.ircd.servers:
            raise RemoteDataInconsistent ("The connecting server on the network is not part of the network.")
        for server in linkedservers:
            if server["name"] in self.factory.ircd.servers:
                raise ServerAlreadyConnected ("A server connected to the remote network is already connected to this network.")
        # Since user and channel data should have been filtered/processed on burst by the receiving server before being broadcast,
        # raise an error if any user data is inconsistent
        # Nickname collision kills must have occurred before notification of the new server, so any problem here indicates that a
        # desyncing of user data has occurred
        for u in users:
            if u["nickname"] in self.factory.ircd.users:
                raise RemoteDataInconsistent ("A user on a connecting remote server matches a user here.")
        # Set up the new server(s)
        newServer = RemoteServer(self.factory.ircd, name, description, nearhop, hopcount)
        for server in self.factory.ircd.servers.itervalues():
            if nearhop in server.remoteServers:
                server.remoteServers.add(name)
                for addingServer in linkedservers:
                    server.remoteServers.add(addingServer["name"])
        # Add new users
        for u in users:
            newUser = RemoteUser(self.factory.ircd, u["nickname"], u["ident"], u["host"], u["gecos"], u["ip"], u["server"], u["secure"], u["signon"], u["ts"])
            for chan in u["channels"]:
                newUser.channels[chan["name"]] = {"status": chan["status"]}
            for modedata in u["mode"]:
                mode = modedata[0]
                param = modedata[1:]
                modetype = self.factory.ircd.user_mode_type[mode]
                if modetype == 0:
                    if mode not in newUser.mode:
                        newUser.mode[mode] = []
                    newUser.mode[mode].append(param)
                elif modetype == 3:
                    newUser.mode[mode] = None
                else:
                    newuser.mode[mode] = param
            self.factory.ircd.users[newUser.nickname] = newUser
        for c in channels:
            if c["name"] not in self.factory.ircd.channels:
                cdata = IRCChannel(self.factory.ircd, c["name"])
                self.factory.ircd.channels[cdata.name] = cdata
            else:
                cdata = self.factory.ircd.channels[c["name"]]
            if c["topic"]:
                cdata.setTopic(c["topic"], c["topicsetter"])
                cdata.topicTime = datatime.utcfromtimestamp(c["topicts"])
            modeChanges = []
            if "mode" in c:
                oldModes = cdata.mode
                cdata.mode = {}
                for modedata in c["mode"]:
                    mode = modedata[0]
                    param = modedata[1:]
                    modetype = self.factory.ircd.channel_mode_type[mode]
                    if modetype == 0:
                        if mode not in cdata.mode:
                            cdata.mode[mode] = []
                        cdata.mode[mode].append(param)
                    elif modetype == 3:
                        cdata.mode[mode] = None
                    else:
                        cdata.mode[mode] = param
                for mode, param in oldModes.iteritems():
                    modetype = self.factory.ircd.channel_mode_type[mode]
                    if modetype == 0:
                        if mode not in cdata.mode:
                            for item in param:
                                modeChanges.append([False, mode, item])
                        else:
                            for item in param:
                                if param not in cdata.mode[mode]:
                                    modeChanges.append([False, mode, item])
                    else:
                        if mode not in cdata.mode:
                            if modetype == 1:
                                modeChanges.append([False, mode, param])
                            else:
                                modeChanges.append([False, mode, None])
                for mode, param in cdata.mode:
                    modetype = self.factory.ircd.channel_mode_type[mode]
                    if modetype == 0:
                        if mode not in oldModes:
                            for item in param:
                                modeChanges.append([True, mode, item])
                        else:
                            for item in param:
                                if param not in oldModes[mode]:
                                    modeChanges.append([True, mode, item])
                    else:
                        if mode not in oldModes:
                            modeChanges.append([True, mode, param])
                        elif oldModes[mode] != param:
                            modeChanges.append([True, mode, param])
            chants = datetime.utcfromtimestamp(c["ts"])
            for nick in c["users"]:
                if nick in self.factory.ircd.users:
                    udata = self.factory.ircd.users[nick]
                    cdata.add(udata)
                    if chants <= cdata.created:
                        for status in udata.channels[cdata.name]["status"]:
                            modeChanges.append([True, status, udata.nickname])
                    else:
                        udata.channels[cdata.name]["status"] = ""
            if modeChanges:
                adding = None
                modes = []
                params = []
                for change in modeChanges:
                    if change[0] and adding != "+":
                        modes.append("+")
                        adding = "+"
                    elif not change[0] and adding != "-":
                        modes.append("-")
                        adding = "-"
                    modes.append(change[1])
                    if change[2] is not None:
                        params.append(change[2])
                if params:
                    modestr = "{} {}".format("".join(modes), " ".join(params))
                for user in cdata.users:
                    if user.nickname in self.factory.ircd.localusers: # Don't send this message to users on remote servers who will get this message anyway
                        user.sendMessage("MODE", modestr, to=cdata.name)
        return {}
    AddNewServer.responder(newServer)
    
    def splitServer(self, name):
        if not self.burstComplete:
            raise NotYetBursted ("The initial burst has not yet occurred on this connection.")
        if name not in self.factory.ircd.servers:
            raise ServerNotConnected ("The server splitting from the network was not connected to the network.")
        servinfo = self.factory.ircd.servers[name]
        leavingServers = servinfo.remoteServers
        leavingServers.append(name)
        userList = self.factory.ircd.users.values()
        for user in userList:
            if user.server in leavingServers:
                user.disconnect("Server disconnected from network")
        for servname in leavingServers:
            del self.factory.ircd.servers[servname]
        return {}
    DisconnectServer.responder(splitServer)
    
    def connectionLost(self, reason):
        # TODO: remove all data from this server originating from remote
        if self.name:
            del self.factory.ircd.servers[self.name]
        for action in self.factory.ircd.actions["netsplit"]:
            action()
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