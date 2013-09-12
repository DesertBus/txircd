from twisted.words.protocols import irc
from txircd.modbase import Command

class UserhostCommand(Command):
    def onUse(self, user, data):
        replyList = []
        for nick in data["targetnick"]:
            udata = self.ircd.users[nick]
            replyList.append("{}{}={}{}@{}".format(udata.nickname, "*" if "o" in udata.mode else "", "-" if "away" in udata.metadata["ext"] else "+", udata.username, udata.hostname))
        user.sendMessage(irc.RPL_USERHOST, ":{}".format(" ".join(replyList)))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "USERHOST", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USERHOST", ":Not enough parameters")
            return {}
        nickList = [nick for nick in params[:5] if nick in self.ircd.users]
        return {
            "user": user,
            "targetnick": nickList
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "USERHOST": UserhostCommand()
            }
        }