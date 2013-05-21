from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import VALID_NICKNAME

class SanickCommand(Command):
    def onUse(self, user, data):
        data["targetuser"].nick(data["newnick"])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "SANICK", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SANICK", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.users:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
            return {}
        target = self.ircd.users[params[0]]
        if "o" in target.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You cannot SANICK another oper")
            return {}
        if not VALID_NICKNAME.match(params[1]):
            user.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[1], ":Erroneous nickname")
            return {}
        if params[0] == params[1]:
            return {}
        return {
            "user": user,
            "targetuser": target,
            "newnick": params[1]
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "SANICK": SanickCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["SANICK"]