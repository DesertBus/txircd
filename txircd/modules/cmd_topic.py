from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now

class TopicCommand(Command):
    def onUse(self, user, data):
        cdata = data["targetchan"]
        if "topic" not in data:
            if cdata.topic:
                user.sendMessage(irc.RPL_TOPIC, cdata.name, ":{}".format(cdata.topic))
                user.sendMessage(irc.RPL_TOPICWHOTIME, cdata.name, cdata.topicSetter, str(epoch(cdata.topicTime)))
            else:
                user.sendMessage(irc.RPL_NOTOPIC, cdata.name, "No topic is set")
        else:
            cdata.setTopic(data["topic"], user.nickname)
            for u in cdata.users:
                u.sendMessage("TOPIC", ":{}".format(cdata.topic), to=cdata.name, prefix=user.prefix())
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "TOPIC", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "TOPIC", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return {}
        if params[0] not in user.channels:
            user.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not in that channel")
            return {}
        if len(params) == 1:
            return {
                "user": user,
                "targetchan": self.ircd.channels[params[0]]
            }
        return {
            "user": user,
            "targetchan": self.ircd.channels[params[0]],
            "topic": params[1]
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "TOPIC": TopicCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["TOPIC"]