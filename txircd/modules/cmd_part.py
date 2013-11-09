from twisted.words.protocols import irc
from txircd.modbase import Command

class PartCommand(Command):
    def onUse(self, user, data):
        if "targetchan" not in data:
            return
        reason = data["reason"] if "reason" in data else None
        for channel in data["targetchan"]:
            if user not in channel.users:
                continue
            if reason:
                channel.sendChannelMessage("PART", ":{}".format(reason), prefix=user.prefix())
            else:
                channel.sendChannelMessage("PART", prefix=user.prefix())
            user.leave(channel)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "PART", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters")
            return {}
        channels = params[0].split(",")
        reason = params[1] if len(params) > 1 else None
        chanInstList = []
        for chan in channels:
            if chan not in self.ircd.channels:
                user.sendMessage(irc.ERR_NOSUCHCHANNEL, chan, ":No such channel")
                continue
            cdata = self.ircd.channels[chan]
            if user not in cdata.users:
                user.sendMessage(irc.ERR_NOTONCHANNEL, chan, ":You're not on that channel")
            else:
                chanInstList.append(cdata)
        if reason:
            return {
                "user": user,
                "targetchan": chanInstList,
                "reason": reason
            }
        return {
            "user": user,
            "targetchan": chanInstList
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "PART": PartCommand()
            }
        }