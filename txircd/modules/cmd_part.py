from twisted.words.protocols import irc
from txircd.modbase import Command

class PartCommand(Command):
    def onUse(self, user, data):
        if "targetchan" not in data:
            return
        for channel in data["targetchan"]:
            for u in channel.users:
                u.sendMessage("PART", ":{}".format(data["reason"]), to=channel.name, prefix=user.prefix())
            user.leave(channel)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "PART", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters")
            return {}
        channels = params[0].split(",")
        reason = params[1] if len(params) > 1 else user.nickname
        delChan = []
        for chan in channels:
            if chan not in self.ircd.channels:
                user.sendMessage(irc.ERR_NOSUCHCHANNEL, chan, ":No such channel")
                delChan.append(chan)
            elif chan not in user.channels:
                user.sendMessage(irc.ERR_NOTONCHANNEL, chan, ":You're not on that channel")
                delChan.append(chan)
        for chan in delChan:
            channels.remove(chan)
        chanInstList = []
        for chan in channels:
            chanInstList.append(self.ircd.channels[chan])
        return {
            "user": user,
            "targetchan": chanInstList,
            "reason": reason
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
    
    def cleanup(self):
        del self.ircd.commands["PART"]