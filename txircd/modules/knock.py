from twisted.words.protocols import irc
from txircd.modbase import Command, Mode

irc.RPL_KNOCK = "710"
irc.RPL_KNOCKDLVR = "711"
irc.ERR_TOOMANYKNOCK = "712"
irc.ERR_CHANOPEN = "713"
irc.ERR_KNOCKONCHAN = "714"

class KnockCommand(Command):
    def onUse(self, user, data):
        cdata = data["targetchan"]
        if "knocks" not in user.cache:
            user.cache["knocks"] = []
        user.cache["knocks"].append(cdata.name)
        reason = data["reason"]
        for u in cdata.users.iterkeys():
            if u.hasAccess(cdata, self.ircd.servconfig["channel_minimum_level"]["INVITE"] if "channel_minimum_level" in self.ircd.servconfig and "INVITE" in self.ircd.servconfig["channel_minimum_level"] else "o"):
                u.sendMessage(irc.RPL_KNOCK, cdata.name, user.prefix(), ":{}".format(reason))
        user.sendMessage(irc.RPL_KNOCKDLVR, cdata.name, ":Your KNOCK has been delivered")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "KNOCK", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "KNOCK", ":Not enough parameters")
            return {}
        if params[0] not in self.ircd.channels:
            user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
            return {}
        cdata = self.ircd.channels[params[0]]
        if user in cdata.users:
            user.sendMessage(irc.ERR_KNOCKONCHAN, cdata.name, ":You are already on that channel")
            return {}
        if "i" not in cdata.mode:
            user.sendMessage(irc.ERR_CHANOPEN, cdata.name, ":Channel is open")
            return {}
        if "knocks" in user.cache and cdata.name in user.cache["knocks"]:
            user.sendMessage(irc.ERR_TOOMANYKNOCK, cdata.name, ":Too many KNOCKs (user)")
            return {}
        return {
            "user": user,
            "targetchan": cdata,
            "reason": " ".join(params[1:]) if len(params) > 1 else "has asked for an invite"
        }
    
    def removeChanKnocks(self, channel):
        for user in self.ircd.users.itervalues():
            if "knocks" not in user.cache:
                continue
            if channel.name in user.cache["knocks"]:
                user.cache["knocks"].remove(channel.name)
    
    def removeKnockOnInvite(self, command, data):
        if command != "INVITE":
            return
        targetUser = data["targetuser"]
        targetChan = data["targetchan"]
        if "knocks" in targetUser.cache and targetChan.name in targetUser.cache["knocks"]:
            targetUser.cache["knocks"].remove(targetChan.name)

class NoknockMode(Mode):
    def checkPermission(self, user, cmd, data):
        if "targetchan" not in data:
            return data
        cdata = data["targetchan"]
        if cmd == "KNOCK" and "K" in cdata.mode:
            user.sendMessage(irc.ERR_TOOMANYKNOCK, cdata.name, ":Channel is +K")
            return {}
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.knockCmd = None
    
    def spawn(self):
        self.knockCmd = KnockCommand()
        return {
            "commands": {
                "KNOCK": self.knockCmd
            },
            "actions": {
                "chandestroy": self.knockCmd.removeChanKnocks,
                "commandextra": self.knockCmd.removeKnockOnInvite
            },
            "modes": {
                "cnK": NoknockMode()
            },
            "common": True
        }
    
    def cleanup(self):
        del self.ircd.commands["KNOCK"]
        self.ircd.actions["chandestroy"].remove(self.knockCmd.removeChanKnocks)
        self.ircd.actions["commandextra"].remove(self.knockCmd.removeKnockOnInvite)
        self.ircd.removeMode("cnK")