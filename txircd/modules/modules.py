from twisted.words.protocols import irc
from txircd.modbase import Command

irc.RPL_MODLIST = "702"
irc.RPL_ENDOFMODLIST = "703"

class ModulesCommand(Command):
    def onUse(self, user, data):
        mod_list = sorted(self.ircd.modules.keys())
        for modname in mod_list:
            user.sendMessage(irc.RPL_MODLIST, ":{}".format(modname))
        user.sendMessage(irc.RPL_ENDOFMODLIST, ":End of MODULES list")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "MODULES", ":You have not registered")
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
                "MODULES": ModulesCommand()
            }
        }