from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.server import IntroduceServer, ModuleMessage, ServerProtocol, protocol_version

class ConnectCommand(Command):
    def onUse(self, user, data):
        if "sourceserver" not in data or "sourceserver" == self.ircd.name:
            try:
                self.ircd.connect_server(data["destserver"])
                user.sendMessage("NOTICE", ":*** Connecting to {}".format(data["destserver"]))
            except RuntimeError as ex:
                user.sendMessage("NOTICE", ":*** Connection to {} failed: {}".format(data["destserver"], ex))
        else:
            server = self.ircd.servers[data["sourceserver"]]
            server.callRemote(ModuleMessage, destserver=server.name, type="ServerConnect", args=[user.uuid, data["destserver"]])
    
    def processParams(self, user, params):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "CONNECT", ":Not enough parameters")
            return {}
        if len(params) >= 2:
            if params[0] not in self.ircd.servers:
                user.sendMessage(irc.ERR_NOSUCHSERVER, params[0], ":No such server")
                return {}
            if params[1] in self.ircd.servers:
                server = self.ircd.servers[params[1]]
                user.sendMessage(irc.ERR_NOSUCHSERVER, server.name, ":The server is already connected to {}".format(server.nearHop)) # Steal this numeric because I can't find a better one
                return {}
            return {
                "user": user,
                "sourceserver": params[0],
                "destserver": params[1]
            }
        if params[0] in self.ircd.servers:
            server = self.ircd.servers[params[0]]
            user.sendMessage(irc.ERR_NOSUCHSERVER, server.name, ":The server is already connected to {}".format(server.nearHop))
        return {
            "user": user,
            "destserver": params[0]
        }
    
    def remoteConnect(self, command, args):
        user = self.ircd.userid[args[0]] if args[0] in self.ircd.userid else None
        try:
            self.ircd.connect_server(args[1])
            user.sendMessage("NOTICE", ":*** Connecting to {}".format(args[1]))
        except RuntimeError as ex:
            user.sendMessage("NOTICE", ":*** Connection to {} failed: {}".format(args[1], ex))

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.connect_cmd = None
    
    def spawn(self):
        self.connect_cmd = ConnectCommand()
        return {
            "commands": {
                "CONNECT": self.connect_cmd
            },
            "server": {
                "ServerConnect": self.connect_cmd.remoteConnect
            }
        }