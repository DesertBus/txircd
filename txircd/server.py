from twisted.internet.protocol import Factory
from twisted.protocols.amp import AMP, Command, Integer, String, AmpList, ListOf, IncompatibleVersions
from txircd.utils import CaseInsensitiveDictionary, epoch, now

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
    
    def __init__(self, ircd, nick, ident, host, gecos, ip, server, secure):
        self.ircd = ircd
        self.socket = self.RemoteSocket(secure)
        self.password = None
        self.nickname = nick
        self.username = ident
        self.realname = gecos
        self.hostname = host
        self.ip = ip
        self.server = server
        self.signon = now()
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
    def __init__(self):
        self.ircd = self.factory.ircd
        self.burstComplete = False # TODO: set this to True somewhere
        self.burstStatus = []
        self.name = None
        self.remoteServers = []
    
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
        for udata in users:
            if udata["nickname"] in self.ircd.users: # a user with the same nickname is already connected
                ourudata = self.ircd.users[udata["nickname"]]
                ourts = epoch(ourudata.nicktime)
                if ourts == udata["ts"]: # older user wins; if same, they both die
                    ourudata.disconnect("Nickname collision")
                    continue
                elif ourts > udata["ts"]:
                    ourudata.disconnect("Nickname collision")
                else:
                    continue # skip adding the remote user since they'll die on the remote server
            newUser = RemoteUser(self.ircd, udata["nickname"], udata["ident"], udata["host"], udata["gecos"], udata["ip"], self.name, udata["secure"])
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
            
        return {}
    BurstData.responder(burstData)
    
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

class ServerFactory(Factory):
    protocol = ServerProtocol
    
    def __init__(self, ircd):
        self.ircd = ircd