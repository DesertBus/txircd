from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary, VALID_NICKNAME
from fnmatch import fnmatch

irc.RPL_STATSQLINE = "217"

class QlineCommand(Command):
    def __init__(self):
        self.banList = CaseInsensitiveDictionary()
    
    def onUse(self, user, data):
        mask = data["mask"]
        if "reason" in data:
            self.banList[mask] = {
                "setter": user.nickname,
                "created": epoch(now()),
                "duration": data["duration"],
                "reason": data["reason"]
            }
            user.sendMessage("NOTICE", ":*** Q:Line set on {}, to expire in {} seconds".format(mask, data["duration"]))
            if "*" not in mask and "?" not in mask:
                if mask in self.ircd.users:
                    self.ircd.users[mask].disconnect("Q:Lined: {}".format(data["reason"]))
            else:
                now_banned = {}
                for user in self.ircd.users.itervalues():
                    reason = self.match_qline(user)
                    if reason:
                        now_banned[user] = reason
                for user, reason in now_banned.iteritems():
                    user.disconnect("Q:Lined: {}".format(reason))
        else:
            del self.banList[mask]
            user.sendMessage("NOTICE", ":*** Q:Line removed on {}".format(mask))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "QLINE", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
            return {}
        self.expire_qlines()
        banmask = params[0]
        if banmask[0] == "-":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
                return {}
            if banmask not in self.banList:
                user.sendMessage("NOTICE", ":*** There is not a q:line set on {}; check /stats Q for a list of existing q:lines".format(banmask))
                return {}
            return {
                "user": user,
                "mask": banmask
            }
        if len(params) < 3 or not params[2]:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
            return {}
        if banmask[0] == "+":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "QLINE", ":Not enough parameters")
                return {}
        if banmask in self.banList:
            user.sendMessage("NOTICE", ":*** Q:line already exists for {}!  Check /stats Q for a list of existing q:lines.".format(params[0]))
            return {}
        bancheck = banmask.replace("*", "")
        if not bancheck or ("*" in banmask and bancheck == "?"):
            user.sendMessage("NOTICE", ":*** That q:line will match all nicks!  Please check your nick mask and try again.")
            return {}
        if not VALID_NICKNAME.match(params[0].replace("*", "").replace("?", "a")):
            user.sendMessage("NOTICE", ":*** That isn't a valid nick mask and won't match any nicks.  Please check your nick mask and try again.")
            return {}
        return {
            "user": user,
            "mask": banmask,
            "duration": parse_duration(params[1]),
            "reason": " ".join(params[2:])
        }
    
    def statsList(self, cmd, data):
        if cmd != "STATS":
            return
        if data["statstype"] != "Q":
            return
        udata = data["user"]
        self.expire_qlines()
        for mask, linedata in self.banList.iteritems():
            udata.sendMessage(irc.RPL_STATSQLINE, ":{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
    
    def check_register(self, user):
        self.expire_qlines()
        reason = self.match_qline(user)
        if not reason:
            return True
        user.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
        user.sendMessage("ERROR", ":Closing Link: {} [Q:Lined: {}]".format(user.hostname, reason), to=None, prefix=None)
    
    def match_qline(self, user):
        if "o" in user.mode:
            return None
        lowerNick = irc_lower(user.nickname)
        for mask, linedata in self.banList.iteritems():
            if fnmatch(lowerNick, mask):
                return linedata["reason"]
        return None
    
    def expire_qlines(self):
        current_time = epoch(now())
        expired = []
        for mask, linedata in self.banList.iteritems():
            if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
                expired.append(mask)
        for mask in expired:
            del self.banList[mask]
    
    def blockNick(self, user, command, data):
        if command != "NICK":
            return data
        newNick = data["nick"]
        lowerNick = irc_lower(newNick)
        self.expire_qlines()
        for mask, linedata in self.banList.iteritems():
            if fnmatch(lowerNick, mask):
                user.sendMessage(irc.ERR_ERRONEUSNICKNAME, newNick, ":Invalid nickname: {}".format(linedata["reason"]))
                return {}
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.qlineCmd = None
    
    def spawn(self):
        self.qlineCmd = QlineCommand()
        return {
            "commands": {
                "QLINE": self.qlineCmd
            },
            "actions": {
                "commandextra": [self.qlineCmd.statsList],
                "register": [self.qlineCmd.check_register],
                "commandpermission": [self.qlineCmd.blockNick]
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["QLINE"]
        self.ircd.actions["commandextra"].remove(self.qlineCmd.statsList)
        self.ircd.actions["register"].remove(self.qlineCmd.check_register)
        self.ircd.actions["commandpermission"].remove(self.qlineCmd.blockNick)
    
    def data_serialize(self):
        return [self.qlineCmd.banList._data, {}]
    
    def data_unserialize(self, data):
        for mask, linedata in data.iteritems():
            self.qlineCmd.banList[mask] = linedata