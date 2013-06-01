from twisted.internet.protocol import Factory
from twisted.protocols.amp import AMP, Command, Integer, String, AmpBox, ListOf, IncompatibleVersions
from txircd.utils import CaseInsensitiveDictionary, now

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


# COMMANDS
class IntroduceServer(Command):
    arguments = [
        ("name", String()), # server name
        ("password", String()), # server password specified in configuration
        ("description", String()), # server description
        ("version", Integer()), # protocol version
        ("commonmodules", ListOf(String()))
    ]
    fatalErrors = {
        ServerAlreadyConnected: "SERVER_ALREADY_CONNECTED",
        ServerMismatchedIP: "SERVER_MISMATCHED_IP",
        ServerPasswordIncorrect: "SERVER_PASS_INCORRECT",
        ServerNoLink: "SERVER_NO_LINK",
        ModuleMismatch: "MODULE_MISMATCH"
    }
    requiresAnswer = False

class BurstUsers(Command):
    arguments = [
        ("users", ListOf(AmpBox()))
    ]
    requiresAnswer = False

class BurstChannels(Command):
    arguments = [
        ("channels", ListOf(AmpBox()))
    ]
    requiresAnswer = False


class ServerProtocol(AMP):
    def __init__(self):
        self.ircd = self.factory.ircd
        self.burstComplete = False
        self.burstStatus = []
        self.name = None
    
    def newServer(self, name, password, description, version, commonmodules):
        if version not in compatible_versions:
            raise IncompatibleVersions ("Protocol version {} is not compatible with this version".format(version))
        commonModDiff = commonmodules ^ self.ircd.common_modules
        if commonModDiff:
            raise ModuleMismatch ("Common modules are not matched between servers: {}".format(", ".join(commonModDiff)))
        if name not in self.ircd.servconfig["serverlinks"]:
            raise ServerNoLink ("There is no link data in the configuration file for the server trying to link.")
        linkData = self.ircd.servconfig["serverlinks"][name]
        ip = self.transport.getPeer().host
        if "ip" not in linkData or ip != linkData["ip"]:
            raise ServerMismatchedIP ("The IP address for this server does not match the one in the configuration.")
        if "incoming_password" not in linkData or password != linkData["incoming_password"]:
            raise ServerPasswordIncorrect ("The password provided by the server does not match the one in the configuration.")
        if "handshake" not in self.burstStatus:
            self.callRemote(IntroduceServer, name=self.ircd.servconfig["server_name"], password=linkData["outgoing_password"], description=self.ircd.servconfig["server_description"], version=current_version, commonmodules=self.ircd.common_modules)
        self.burstStatus.append("handshake")
        self.name = name
        self.ircd.servers[name] = self
    IntroduceServer.responder(newServer)
    
    def burstUsers(self, users):
        pass # TODO
    BurstUsers.responder(burstUsers)
    
    def burstChannels(self, channels):
        pass # TODO
    BurstChannels.responder(burstChannels)
    
    def connectionLost(self, reason):
        # TODO: remove all data from this server originating from remote
        del self.ircd.servers[self.name]
        AMP.connectionLost(self, reason)

class ServerFactory(Factory):
    protocol = ServerProtocol
    
    def __init__(self, ircd):
        self.ircd = ircd
    
    # TODO: extend Factory to form ServerFactory as the base for all this; see app.py