from twisted.words.protocols import irc
from txircd.channel import IRCChannel
from txircd.modbase import Command

class SajoinCommand(Command):
    def onUse(self, user, data):
        data["targetuser"].join(data["targetchan"])
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SAJOIN", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SAJOIN", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.users:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
            return {}
        if params[1][0] != "#":
            user.sendMessage(irc.ERR_BADCHANMASK, chan["channel"], ":Bad Channel Mask")
            return {}
        if params[1] in self.ircd.channels:
            cdata = self.ircd.channels[params[1]]
        else:
            cdata = IRCChannel(self.ircd, params[1])
        return {
            "user": user,
            "targetuser": self.ircd.users[params[0]],
            "targetchan": cdata
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "SAJOIN": SajoinCommand()
            }
        }