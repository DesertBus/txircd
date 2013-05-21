from twisted.words.protocols import irc
from txircd.modbase import Command

class RehashCommand(Command):
    def onUse(self, user, data):
        user.sendMessage(irc.RPL_REHASHING, self.ircd.config, ":Rehashing")
        self.ircd.rehash()
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "REHASH", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the required operator privileges")
            return {}
        return {
            "user": user
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "REHASH": RehashCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["REHASH"]