from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.server import ModuleMessage
from txircd.utils import irc_lower
from fnmatch import fnmatch

class RehashCommand(Command):
    def onUse(self, user, data):
        serverMask = irc_lower(data["servers"])
        if fnmatch(irc_lower(self.ircd.name), serverMask):
            user.sendMessage(irc.RPL_REHASHING, self.ircd.config, ":Rehashing")
            self.ircd.rehash()
        for server in self.ircd.servers.itervalues():
            if fnmatch(irc_lower(server.name), serverMask):
                server.callRemote(ModuleMessage, destserver=server.name, type="Rehash", args=[])
                user.sendMessage(irc.RPL_REHASHING, self.ircd.config, ":Rehashing {}".format(server.name))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "REHASH", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return {}
        if params:
            return {
                "user": user,
                "servers": params[0]
            }
        return {
            "user": user,
            "servers": self.ircd.name
        }
    
    def remoteRehash(self, command, args):
        self.ircd.rehash()

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.rehash_cmd = None
    
    def spawn(self):
        self.rehash_cmd = RehashCommand()
        return {
            "commands": {
                "REHASH": self.rehash_cmd
            },
            "server": {
                "Rehash": self.rehash_cmd.remoteRehash
            }
        }