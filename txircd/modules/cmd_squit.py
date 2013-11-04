from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.server import ModuleMessage

class SQuitCommand(Command):
    def onUse(self, user, data):
        if data["server"].nearHop == self.ircd.name:
            data["server"].transport.loseConnection()
        else:
            self.ircd.servers[data["server"].nearHop].callRemote(ModuleMessage, destserver=data["server"].nearHop, type="ServerQuit", args=[data["server"].name])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SQUIT", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SQUIT", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.servers:
            user.sendMessage(irc.ERR_NOSUCHSERVER, params[0], ":No such server")
            return {}
        server = self.ircd.servers[params[0]]
        return {
            "user": user,
            "server": server
        }
    
    def remoteQuit(self, command, args):
        if args[0] not in self.ircd.servers:
            return
        server = self.ircd.servers[args[0]]
        if server.nearHop == self.ircd.name:
            server.transport.loseConnection()

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.squit_cmd = None
    
    def spawn(self):
        self.squit_cmd = SQuitCommand()
        return {
            "commands": {
                "SQUIT": self.squit_cmd
            },
            "server": {
                "ServerQuit": self.squit_cmd.remoteQuit
            }
        }