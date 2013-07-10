from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import now

class SatopicCommand(Command):
    def onUse(self, user, data):
        cdata = data["targetchan"]
        cdata.setTopic(data["topic"], user.nickname)
        cdata.sendChannelMessage("TOPIC", ":{}".format(cdata.topic), prefix=user.prefix())
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "SATOPIC", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SATOPIC", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return {}
        return {
            "user": user,
            "targetchan": self.ircd.channels[params[0]],
            "topic": " ".join(params[1:])
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "SATOPIC": SatopicCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["SATOPIC"]