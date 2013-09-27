from twisted.words.protocols import irc
from txircd.modbase import Command
import string

class UserCommand(Command):
    def onUse(self, user, data):
        if not user.username:
            user.registered -= 1
        user.setUsername(data["ident"])
        user.setRealname(data["gecos"])
        if user.registered == 0:
            user.register()
    
    def processParams(self, user, params):
        if user.registered == 0:
            user.sendMessage(irc.ERR_ALREADYREGISTRED, ":You may not reregister")
            return {}
        if params and len(params) < 4:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Not enough parameters")
            return {}
        ident = filter(lambda x: x in string.ascii_letters + string.digits + "-_", params[0][:12])
        if not ident:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Your username is not valid")
            return {}
        return {
            "user": user,
            "ident": ident,
            "gecos": params[3]
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "USER": UserCommand()
            }
        }