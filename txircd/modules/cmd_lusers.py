from twisted.words.protocols import irc
from txircd.modbase import Command

class LusersCommand(Command):
    def onUse(self, user, data):
        user.send_lusers()
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "LUSERS", ":You have not registered")
            return {}
        return {
            "user": user
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.lusersCmd = None
    
    def spawn(self):
        self.lusersCmd = LusersCommand()
        return {
            "commands": {
                "LUSERS": self.lusersCmd
            }
        }