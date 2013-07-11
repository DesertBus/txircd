from twisted.words.protocols import irc
from txircd.modbase import Command

class InfoCommand(Command):
    def onUse(self, user, data):
        user.sendMessage(irc.RPL_INFO, ":{}".format(self.ircd.version))
        user.sendMessage(irc.RPL_INFO, ":Developed by the Desert Bus for Hope Engineering Team")
        user.sendMessage(irc.RPL_INFO, ": -")
        user.sendMessage(irc.RPL_INFO, ":Original txircd by Fugiman, ElementalAlchemist, and ojii")
        user.sendMessage(irc.RPL_INFO, ":Modular txircd by ElementalAlchemist and Fugiman")
        user.sendMessage(irc.RPL_ENDOFINFO, ":End of /INFO list")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "INFO", ":You have not registered")
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
                "INFO": InfoCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["INFO"]