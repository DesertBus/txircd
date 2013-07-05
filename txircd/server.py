from twisted.internet.defer import Deferred
from twisted.internet.protocol import Factory, ClientFactory
from twisted.protocols.amp import AMP, Command, Integer, String, Boolean, AmpList, ListOf, IncompatibleVersions
from txircd.channel import IRCChannel
from txircd.utils import CaseInsensitiveDictionary, epoch, irc_lower, now
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
    
    def __init__(self, ircd, uuid, nick, ident, host, gecos, ip, server, secure, signonTime, nickTime):
        self.ircd = ircd
        self.socket = self.RemoteSocket(secure)
        self.uuid = uuid
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
    
    def disconnect(self, reason, sourceServer = None):
        quitdest = set()
        exitChannels = []
        for channel in self.ircd.channels.itervalues():
            if self in channel.users:
                exitChannels.append(channel)
        for channel in exitChannels:
            self.leave(channel)
            for u in channel.users.iterkeys():
                quitdest.add(u)
        udata = self.ircd.users[self.nickname]
        if udata == self:
            del self.ircd.users[self.nickname]
        del self.ircd.userid[self.uuid]
        for user in quitdest:
            user.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=self.prefix())
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name and server.name != sourceServer:
                server.callRemote(RemoveUser, user=self.uuid, reason=reason)
    
    def sendMessage(self, command, *parameter_list, **kw):
        pass # TODO
    
    def setMetadata(self, namespace, key, value):
        self.ircd.servers[self.server].callRemote(RequestMetadata, user=self.uuid, namespace=namespace, key=key, value=value)
    
    def delMetadata(self, namespace, key):
        self.ircd.servers[self.server].callRemote(RequestMetadata, user=self.uuid, namespace=namespace, key=key, value="")
    
    def prefix(self):
        return "{}!{}@{}".format(self.nickname, self.username, self.hostname)
    
    def hasAccess(self, channel, level):
        if self not in channel.users or level not in self.ircd.prefixes:
            return None
        status = channel.users[self]
        if not status:
            return False
        return self.ircd.prefixes[status[0]][1] >= self.ircd.prefixes[level][1]
    
    def setMode(self, user, modes, params, displayPrefix = None):
        if user:
            source = user.prefix()
        elif displayPrefix:
            source = displayPrefix
        else:
            source = self.ircd.name
        self.ircd.servers[self.server].callRemote(RequestSetMode, user=self.uuid, source=source, modestring=modes, params=params)
    
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
    
    def join(self, channel):
        self.ircd.servers[self.server].callRemote(RequestJoinChannel, channel=channel.name, user=self.uuid)
    
    def part(self, channel, reason):
        self.ircd.servers[self.server].callRemote(RequestPartChannel, channel=channel.name, user=self.uuid)
    
    def leave(self, channel):
        pass
    
    def nick(self, newNick):
        if newNick in self.ircd.users:
            return
        self.ircd.servers[self.server].callRemote(RequestNick, user=self.uuid, newnick=newNick)

class RemoteServer(object):
    def __init__(self, ircd, name, desc, nearestServer, hopCount):
        self.ircd = ircd
        self.name = name
        self.description = desc
        self.nearHop = nearestServer
        self.burstComplete = True
        self.remoteServers = set()
        self.hopCount = hopCount
    
    def callRemote(self, command, *args, **kw):
        server = self
        while server.nearHop != self.ircd.name and server.nearHop in self.ircd.servers:
            server = self.ircd.servers[server.nearHop]
        if server.name in self.ircd.servers:
            server.callRemote(command, *args, **kw) # If the parameters are such that they indicate the target properly, this will be forwarded to the proper server.


# ERRORS
class HandshakeAlreadyComplete(Exception):
    pass

class HandshakeNotYetComplete(Exception):
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

class ServerNotConnected(Exception):
    pass

class NoSuchTarget(Exception):
    pass

class NoSuchUser(Exception):
    pass

class NoSuchServer(Exception):
    pass

class NoSuchChannel(Exception):
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

class AddNewServer(Command):
    arguments = [
        ("name", String()),
        ("description", String()),
        ("hopcount", Integer()),
        ("nearhop", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE"
    }
    fatalErrors = {
        ServerAlreadyConnected: "SERVER_ALREADY_CONNECTED" # If this error is present, the servers are already desynced, so have them fully disconnect and try again
    }
    requiresAnswer = False

class DisconnectServer(Command):
    arguments = [
        ("name", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE"
    }
    fatalErrors = {
        ServerNotConnected: "NO_SUCH_SERVER"
    }
    requiresAnswer = False

class RequestMetadata(Command):
    arguments = [
        ("user", String()),
        ("namespace", String()),
        ("key", String()),
        ("value", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class SetMetadata(Command):
    arguments = [
        ("target", String()),
        ("targetts", Integer()),
        ("namespace", String()),
        ("key", String()),
        ("value", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchTarget: "NO_SUCH_TARGET"
    }
    requiresAnswer = False

class ConnectUser(Command):
    arguments = [
        ("uuid", String()),
        ("nick", String()),
        ("ident", String()),
        ("host", String()),
        ("gecos", String()),
        ("ip", String()),
        ("server", String()),
        ("secure", Boolean()),
        ("signon", Integer()),
        ("nickts", Integer())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchServer: "NO_SUCH_SERVER"
    }
    requiresAnswer = False

class RemoveUser(Command):
    arguments = [
        ("user", String()),
        ("reason", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class RequestJoinChannel(Command):
    arguments = [
        ("channel", String()),
        ("user", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class JoinChannel(Command):
    arguments = [
        ("channel", String()),
        ("user", String()),
        ("chants", Integer())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class RequestPartChannel(Command):
    arguments = [
        ("channel", String()),
        ("user", String()),
        ("reason", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER",
        NoSuchChannel: "NO_SUCH_CHANNEL"
    }
    requiresAnswer = False

class PartChannel(Command):
    arguments = [
        ("channel", String()),
        ("user", String()),
        ("reason", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER",
        NoSuchChannel: "NO_SUCH_CHANNEL"
    }
    requiresAnswer = False

class LeaveChannel(Command):
    arguments = [
        ("channel", String()),
        ("user", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER",
        NoSuchChannel: "NO_SUCH_CHANNEL"
    }
    requiresAnswer = False

class RequestSetMode(Command):
    arguments = [
        ("user", String()),
        ("source", String()),
        ("modestring", String()),
        ("params", ListOf(String()))
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class SetMode(Command):
    arguments = [
        ("target", String()),
        ("targetts", Integer()),
        ("source", String()),
        ("modestring", String()),
        ("params", ListOf(String()))
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchTarget: "NO_SUCH_TARGET"
    }
    requiresAnswer = False

class SetTopic(Command):
    arguments = [
        ("channel", String()),
        ("chants", Integer()),
        ("topic", String()),
        ("topicsetter", String()),
        ("topicts", Integer())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchChannel: "NO_SUCH_CHANNEL"
    }
    requiresAnswer = False

class RequestNick(Command):
    arguments = [
        ("user", String()),
        ("newnick", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False

class ChangeNick(Command):
    arguments = [
        ("user", String()),
        ("newnick", String())
    ]
    errors = {
        HandshakeNotYetComplete: "HANDSHAKE_NOT_COMPLETE",
        NoSuchUser: "NO_SUCH_USER"
    }
    requiresAnswer = False


class ServerProtocol(AMP):
    def __init__(self, ircd):
        self.ircd = ircd
        self.sentDataBurst = None # Just to make sure it can only be sent once
        self.name = None
        self.description = None
        self.remoteServers = set()
        self.localOrigin = False
        self.nearHop = self.ircd.name
        self.nearRemoteLink = self.ircd.name
        self.hopCount = 1
    
    def serverHandshake(self, name, password, description, version, commonmodules):
        if self.name is not None:
            raise HandshakeAlreadyComplete ("The server handshake has already been completed between these servers.")
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
        if self.sentDataBurst is None:
            self.callRemote(IntroduceServer, name=self.ircd.name, password=linkData["outgoing_password"], description=self.ircd.servconfig["server_description"], version=protocol_version, commonmodules=self.ircd.common_modules)
            self.sentDataBurst = False
        self.sendBurstData()
        self.name = name
        self.description = description
        self.ircd.servers[self.name] = self
        return {}
    IntroduceServer.responder(serverHandshake)
    
    def sendBurstData(self):
        if self.sentDataBurst is not False:
            return
        self.sentDataBurst = True
        serverOrder = []
        while len(serverOrder) < len(self.ircd.servers):
            for server in self.ircd.servers.itervalues():
                if server in serverOrder:
                    continue
                if server.nearHop == self.ircd.name or server.nearHop in serverOrder:
                    serverOrder.append(server)
        for server in serverOrder:
            self.callRemote(AddNewServer, name=server.name, description=server.description, hopcount=server.hopCount, nearhop=server.nearHop)
        for u in self.ircd.users.itervalues():
            self.callRemote(ConnectUser, nick=u.nickname, ident=u.username, host=u.hostname, gecos=u.realname, ip=u.ip, server=u.server, secure=u.socket.secure, signon=epoch(u.signon), nickts=epoch(u.nicktime))
            modes = []
            params = []
            for mode, param in u.mode.iteritems():
                if self.ircd.user_mode_type[mode] == 0:
                    for item in param:
                        modes.append(mode)
                        params.append(item)
                elif param is None:
                    modes.append(mode)
                else:
                    modes.append(mode)
                    params.append(param)
            self.callRemote(SetMode, target=u.nickname, targetts=epoch(u.signon), source=u.prefix(), modestring="+{}".format("".join(modes)), params=params)
            for namespace, data in u.metadata.iteritems():
                for key, value in data.iteritems():
                    self.callRemote(SetMetadata, target=u.nickname, targetts=epoch(u.signon), namespace=namespace, key=key, value=value)
        for chan in self.ircd.channels.itervalues():
            modes = []
            params = []
            for u, status in chan.user.iteritems():
                self.callRemote(JoinChannel, channel=chan.name, nick=u.nickname, chants=epoch(chan.created))
                for mode in status:
                    modes.append(mode)
                    params.append(u.nickname)
            for mode, param in chan.mode.iteritems():
                if self.ircd.channel_mode_type[mode] == 0:
                    for item in param:
                        modes.append(mode)
                        params.append(item)
                elif param is None:
                    modes.append(mode)
                else:
                    modes.append(mode)
                    params.append(param)
            self.callRemote(SetMode, target=chan.name, targetts=epoch(chan.created), source="", modestring="+{}".format("".join(modes)), params=params)
            if chan.topic:
                self.callRemote(SetTopic, channel=chan.name, chants=epoch(chan.created), topic=chan.topic, topicsetter=chan.topicSetter, topicts=epoch(chan.topicTime))
            for namespace, data in chan.metadata.iteritems():
                for key, value in data.iteritems():
                    self.callRemote(SetMetadata, target=chan.name, targetts=epoch(chan.created), namespace=namespace, key=key, value=value)
    
    def newServer(self, name, description, hopcount, nearhop):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        # check for server-related desyncs
        if name in self.ircd.servers:
            raise ServerAlreadyConnected ("The server trying to connect to the network is already connected to the network.")
        
        # Set up the new server(s)
        newServer = RemoteServer(self.ircd, name, description, nearhop, hopcount + 1)
        nearHop = self.ircd.servers[nearhop]
        nearHop.remoteServers.add(name)
        for server in self.ircd.servers.itervalues():
            if nearhop in server.remoteServers:
                server.remoteServers.add(name)
        self.ircd.servers[name] = newServer
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name and server != self:
                # The server is connected to this server but is NOT this server link
                # so that it goes to each server once and does not get sent back where it came from
                server.callRemote(AddNewServer, name=name, description=description, hopcount=hopcount+1, nearhop=nearhop)
        return {}
    AddNewServer.responder(newServer)
    
    def splitServer(self, name):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if name not in self.ircd.servers:
            raise ServerNotConnected ("The server splitting from the network was not connected to the network.")
        servinfo = self.ircd.servers[name]
        leavingServers = servinfo.remoteServers
        leavingServers.add(name)
        userList = self.ircd.users.values()
        for user in userList:
            if user.server in leavingServers:
                user.disconnect("{} {}".format(servinfo.nearHop, servinfo.name))
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
        if self.name:
            self.splitServer(self.name)
        AMP.connectionLost(self, reason)
    
    def requestMetadata(self, user, namespace, key, value):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if user not in self.ircd.userid:
            raise NoSuchUser ("The user we're to update doesn't actually exist.")
        if value:
            self.ircd.userid[user].setMetadata(namespace, key, value) # This is defined in IRCUser to work or RemoteUser to keep passing it on
        else:
            self.ircd.userid[user].delMetadata(namespace, key)
        return {}
    RequestMetadata.responder(requestMetadata)
    
    def setMetadata(self, target, targetts, namespace, key, value):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if target in self.ircd.userid:
            data = self.ircd.users[target]
        elif target in self.ircd.channels:
            data = self.ircd.channels[target]
            if datetime.utcfromtimestamp(targetts) > data.created:
                return {}
        else:
            raise NoSuchTarget ("The specified user or channel is not connected to the network.")
        if not value and key not in data.metadata[namespace]:
            return {}
        if not value:
            oldValue = data.metadata[namespace][key]
            del data.metadata[namespace][key]
            for action in self.ircd.actions["metadataupdate"]:
                action(data, namespace, key, oldValue, "")
        else:
            oldValue = ""
            if key in data.metadata[namespace]:
                oldValue = data.metadata[namespace][key]
            data.metadata[namespace][key] = value
            for action in self.ircd.actions["metadataupdate"]:
                action(data, namespace, key, oldValue, value)
        for server in self.ircd.servers.itervalues():
            if server.nearHop == self.ircd.name and server != self:
                server.callRemote(SetMetadata, target=target, targetts=targetts, namespace=namespace, key=key, value=value)
        return {}
    SetMetadata.responder(setMetadata)
    
    def addUser(self, uuid, nick, ident, host, gecos, ip, server, secure, signon, nickts):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if server not in self.ircd.servers:
            raise NoSuchServer ("The server this user is on is not connected to the network.")
        signontime = datetime.utcfromtimestamp(signon)
        nicktime = datetime.utcfromtimestamp(nickts)
        if nick in self.ircd.users:
            udata = self.ircd.users[nick]
            if nicktime < udata.nicktime:
                udata.disconnect("Nickname collision")
            elif nicktime == udata.nicktime:
                if signontime < udata.signon:
                    udata.disconnect("Nickname collision")
                elif signontime == udata.signon:
                    udata.disconnect("Nickname collision")
                    return {}
                else:
                    return {}
            else:
                return {}
        newUser = RemoteUser(self.ircd, uuid, nick, ident, host, gecos, ip, server, secure, signontime, nicktime)
        self.ircd.users[nick] = newUser
        self.ircd.userid[uuid] = newUser
        for linkedServer in self.ircd.servers.itervalues():
            if linkedServer.nearHop == self.ircd.name and linkedServer != self:
                linkedServer.callRemote(ConnectUser, uuid=uuid, nick=nick, ident=ident, host=host, gecos=gecos, ip=ip, server=server, secure=secure, signon=signon, nickts=nickts)
        return {}
    ConnectUser.responder(addUser)
    
    def removeUser(self, user, reason):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if user not in self.ircd.userid:
            raise NoSuchUser ("The given user is not on the network.")
        self.ircd.userid[user].disconnect(reason, self.name)
        return {}
    RemoveUser.responder(removeUser)
    
    def requestJoin(self, channel, user):
        pass # TODO
    RequestJoinChannel.responder(requestJoin)
    
    def joinChannel(self, channel, user, chants):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if user not in self.ircd.userid:
            raise NoSuchUser ("The given user is not connected to the network.")
        user = self.ircd.userid[user]
        if channel in user.channels:
            return {}
        if channel in self.ircd.channels:
            cdata = self.ircd.channels[channel]
        else:
            cdata = IRCChannel(self.ircd, channel)
        # TODO
        return {}
    JoinChannel.responder(joinChannel)
    
    def requestPart(self, channel, user, reason):
        pass # TODO
    RequestPartChannel.responder(requestPart)
    
    def partChannel(self, channel, user, reason):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if user not in self.ircd.userid:
            raise NoSuchUser ("The given user is not connected to the network.")
        if channel not in self.ircd.channels:
            return {} # If the channel is already destroyed, raising may be from a broadcast throwback
        user = self.ircd.userid[user]
        chan = self.ircd.channels[channel]
        # TODO
        return {}
    PartChannel.responder(partChannel)
    
    def leaveChannel(self, channel, user):
        pass # TODO
    LeaveChannel.responder(leaveChannel)
    
    def requestMode(self, user, source, modestring, params):
        pass # TODO
    RequestSetMode.responder(requestMode)
    
    def setMode(self, target, targetts, source, modestring, params):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if target in self.ircd.channels:
            data = self.ircd.channels[target]
        elif target in self.ircd.userid:
            data = self.ircd.userid[target]
        else:
            raise NoSuchTarget ("The target given does not exist on the network.")
        # TODO
        return {}
    SetMode.responder(setMode)
    
    def setTopic(self, channel, chants, topic, topicsetter, topicts):
        if not self.name:
            raise HandshakeNotYetComplete ("The initial handshake has not occurred over this link.")
        if channel not in self.ircd.channels:
            raise NoSuchChannel ("The specified channel does not exist on this network.")
        cdata = self.ircd.channels[channel]
        chantime = datetime.utcfromtimestamp(chants)
        if cdata.created < chantime:
            return {} # Ignore the change
        topictime = datetime.utcfromtimestamp(topicts)
        if chantime < cdata.created or topictime > cdata.topicTime:
            for action in self.ircd.actions["topic"]:
                action(cdata, topic, topicsetter)
            cdata.topic = topic
            cdata.topicSetter = topicsetter
            cdata.topicTime = topictime
            for u in cdata.users.iterkeys():
                if u.server == self.ircd.name:
                    u.sendMessage("TOPIC", ":{}".format(topic), to=cdata.name, prefix=topicsetter)
        return {}
    SetTopic.responder(setTopic)
    
    def requestNick(self, user, newnick):
        pass # TODO
    RequestNick.responder(requestNick)
    
    def changeNick(self, user, newNick):
        pass # TODO
    ChangeNick.responder(changeNick)

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