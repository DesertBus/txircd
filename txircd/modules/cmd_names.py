from twisted.words.protocols import irc
from txircd.modbase import Command

class NamesCommand(Command):
    def onUse(self, user, data):
        for chan in data["targetchan"]:
            user.report_names(chan)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "NAMES", ":You have not registered")
            return {}
        if params:
            channames = params[0].split(",")
            channels = []
            for chan in channames:
                if chan in self.ircd.channels:
                    channels.append(self.ircd.channels[chan])
                else:
                    user.sendMessage(irc.ERR_NOSUCHNICK, chan, ":No such nick/channel")
        else:
            channels = []
            for chan in self.ircd.channels.itervalues:
                if user in chan.users:
                    channels.append(chan)
        return {
            "user": user,
            "targetchan": channels
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "NAMES": NamesCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["NAMES"]