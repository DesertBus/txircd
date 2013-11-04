from twisted.words.protocols import irc
from txircd.modbase import Command

class InviteCommand(Command):
    def onUse(self, user, data):
        targetUser = data["targetuser"]
        targetChan = data["targetchan"]
        user.sendMessage(irc.RPL_INVITING, targetUser.nickname, targetChan.name)
        targetUser.sendMessage("INVITE", targetChan.name, prefix=user.prefix())
        if "invites" not in targetUser.cache:
            targetUser.cache["invites"] = [targetChan.name]
        else:
            targetUser.cache["invites"].append(targetChan.name)
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "INVITE", ":You have not registered")
            return {}
        if not params or len(params) < 2:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "INVITE", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.users:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
            return {}
        if params[1] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick/channel")
            return {}
        udata = self.ircd.users[params[0]]
        cdata = self.ircd.channels[params[1]]
        if udata in cdata.users:
            user.sendMessage(irc.ERR_USERONCHANNEL, udata.nickname, cdata.name, ":is already on channel")
            return {}
        if user not in cdata.users:
            user.sendMessage(irc.ERR_NOTONCHANNEL, cdata.name, ":You're not on that channel")
            return {}
        if "i" in cdata.mode and not user.hasAccess(cdata, self.ircd.servconfig["channel_minimum_level"]["INVITE"]):
            user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, cdata.name, ":You're not a channel operator")
            return {}
        return {
            "user": user,
            "targetuser": udata,
            "targetchan": cdata
        }
    
    def removeChanInvites(self, channel):
        for user in self.ircd.users.itervalues():
            if "invites" in user.cache and channel.name in user.cache["invites"]:
                user.cache["invites"].remove(channel.name)

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.inviteCmd = None
    
    def spawn(self):
        if "channel_minimum_level" not in self.ircd.servconfig:
            self.ircd.servconfig["channel_minimum_level"] = {}
        if "INVITE" not in self.ircd.servconfig["channel_minimum_level"]:
            self.ircd.servconfig["channel_minimum_level"]["INVITE"] = "o"
        self.inviteCmd = InviteCommand()
        return {
            "commands": {
                "INVITE": self.inviteCmd
            },
            "actions": {
                "chandestroy": self.inviteCmd.removeChanInvites
            }
        }