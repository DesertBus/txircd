from twisted.words.protocols import irc
from txircd.modbase import Command

irc.RPL_ADMINLOC1 = "257"
irc.RPL_ADMINLOC2 = "258"

class AdminCommand(Command):
    def onUse(self, user, data):
        user.sendMessage(irc.RPL_ADMINME, self.ircd.name, ":Administrative info for {}".format(self.ircd.name))
        user.sendMessage(irc.RPL_ADMINLOC1, ":{}".format(self.ircd.servconfig["admin_info_server"]))
        user.sendMessage(irc.RPL_ADMINLOC2, ":{}".format(self.ircd.servconfig["admin_info_organization"]))
        user.sendMessage(irc.RPL_ADMINEMAIL, ":{}".format(self.ircd.servconfig["admin_info_person"]))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "ADMIN", ":You have not registered")
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
                "ADMIN": AdminCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["ADMIN"]