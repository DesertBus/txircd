from twisted.words.protocols import irc
from txircd.modbase import Command

class KickCommand(Command):
    def onUse(self, user, data):
        if "targetchan" not in data or "targetuser" not in data:
            return
        cdata = data["targetchan"]
        udata = data["targetuser"]
        cdata.sendChannelMessage("KICK", udata.nickname, ":{}".format(data["reason"]), prefix=user.prefix())
        udata.leave(cdata)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "KICK", ":You have not registered")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "KICK", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return {}
        cdata = self.ircd.channels[params[0]]
        if not user.hasAccess(cdata, self.ircd.servconfig["channel_minimum_level"]["KICK"]):
            user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You must have channel operator access to kick users")
            return {}
        if params[1] not in self.ircd.users:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick")
            return {}
        udata = self.ircd.users[params[1]]
        if udata not in cdata.users:
            user.sendMessage(irc.ERR_USERNOTINCHANNEL, udata.nickname, cdata.name, ":They are not on that channel")
            return {}
        if len(params) < 3 or not params[2]:
            reason = user.nickname
        else:
            reason = params[2]
        return {
            "user": user,
            "targetchan": cdata,
            "targetuser": self.ircd.users[params[1]],
            "reason": reason
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        if "channel_minimum_level" not in self.ircd.servconfig:
            self.ircd.servconfig["channel_minimum_level"] = {}
        if "KICK" not in self.ircd.servconfig["channel_minimum_level"]:
            self.ircd.servconfig["channel_minimum_level"]["KICK"] = "o"
        return {
            "commands": {
                "KICK": KickCommand()
            }
        }