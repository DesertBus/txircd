from twisted.words.protocols import irc
from txircd.modbase import Command

class SamodeCommand(Command):
    def onUse(self, user, data):
        if "targetchan" in data:
            cdata = data["targetchan"]
            modesSet = cdata.setMode(None, data["modes"], data["params"], user.prefix())
            user.sendMessage("NOTICE", ":*** SAMODE used on {}; set {}".format(cdata.name, modesSet))
        elif "targetuser" in data:
            udata = data["targetuser"]
            modesSet = udata.setMode(user, data["modes"], data["params"])
            user.sendMessage("NOTICE", ":*** SAMODE used on {}; set {}".format(cdata.name, modesSet))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SAMODE", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SAMODE", ":Not enough parameters")
            return {}
        
        if params[0] in self.ircd.users:
            return {
                "user": user,
                "targetuser": self.ircd.users[params[0]],
                "modes": params[1],
                "params": params[2:]
            }
        
        if params[0] in self.ircd.channels:
            return {
                "user": user,
                "targetchan": self.ircd.channels[params[0]],
                "modes": params[1],
                "params": params[2:]
            }
        user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
        return {}

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "SAMODE": SamodeCommand()
            }
        }