from twisted.words.protocols import irc
from txircd.modbase import Command

class SakickCommand(Command):
    def onUse(self, user, data):
        cdata = data["targetchan"]
        udata = data["targetuser"]
        reason = data["reason"]
        cdata.sendChannelMessage("KICK", udata.nickname, ":{}".format(reason), prefix=user.prefix())
        udata.leave(cdata)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "SAKICK", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SAKICK", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return {}
        if params[1] not in self.ircd.users:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick")
            return {}
        cdata = self.ircd.channels[params[0]]
        udata = self.ircd.users[params[1]]
        if udata not in cdata.users:
            user.sendMessage(irc.ERR_USERNOTINCHANNEL, udata.nickname, cdata.name, ":They are not on that channel")
            return {}
        if len(params) >= 3:
            reason = " ".join(params[2:])
        else:
            reason = user.nickname
        return {
            "user": user,
            "targetchan": self.ircd.channels[params[0]],
            "targetuser": self.ircd.users[params[1]],
            "reason": reason
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "SAKICK": SakickCommand()
            }
        }