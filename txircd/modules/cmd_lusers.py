from twisted.words.protocols import irc
from txircd.modbase import Command

class LusersCommand(Command):
    def onUse(self, user, data):
        user.send_lusers()
    
    def processParams(self, user, params):
        if user.registered > 0:
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
    
    def cleanup(self):
        del self.ircd.commands["LUSERS"]