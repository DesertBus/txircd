from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.channel import IRCChannel

class JoinCommand(Command):
    def onUse(self, user, data):
        if "targetchan" not in data or not data["targetchan"]:
            return
        for chan in data["targetchan"]:
            user.join(chan)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "JOIN", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters")
            return {}
        channels = params[0].split(",")
        keys = params[1].split(",") if len(params) > 1 else []
        joining = []
        for i in range(0, len(channels)):
            channame = channels[i][:64]
            if channame[0] != "#":
                user.sendMessage(irc.ERR_BADCHANMASK, channame, ":Bad Channel Mask")
                continue
            if channame in self.ircd.channels:
                cdata = self.ircd.channels[channame]
            else:
                cdata = IRCChannel(self.ircd, channame)
            joining.append({"channel": cdata, "key": keys[i] if i < len(keys) else None})
        remove = []
        for chan in joining:
            if user in chan["channel"].users:
                remove.append(chan)
        for chan in remove:
            joining.remove(chan)
        channels = []
        keys = []
        for chan in joining:
            channels.append(chan["channel"])
            keys.append(chan["key"])
        return {
            "user": user,
            "targetchan": channels,
            "keys": keys,
            "moreparams": params[2:]
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "JOIN": JoinCommand()
            }
        }