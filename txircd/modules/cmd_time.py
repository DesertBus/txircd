from twisted.words.protocols import irc
from txircd.modbase import Command

class TimeCommand(Command):
    def onUse(self, user, data):
        user.sendMessage(irc.RPL_TIME, self.ircd.name, ":{}".format(now()))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "TIME", ":You are not registered")
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
                "TIME": TimeCommand()
            }
        }