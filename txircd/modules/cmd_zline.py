from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, parse_duration, CaseInsensitiveDictionary
from fnmatch import fnmatch

irc.RPL_STATSZLINE = "223"

class ZlineCommand(Command):
    def __init__(self):
        self.banList = CaseInsensitiveDictionary()
    
    def onUse(self, user, data):
        if "reason" in data:
            self.banList[data["mask"]] = {
                "setter": user.nickname,
                "created": epoch(now()),
                "duration": data["duration"],
                "reason": data["reason"]
            }
            user.sendMessage("NOTICE", ":*** Z:Line set on {}, to expire in {} seconds".format(data["mask"], data["duration"]))
            now_banned = {}
            for uid, udata in self.ircd.users.iteritems():
                reason = self.match_zline(udata)
                if reason:
                    now_banned[uid] = reason
            for uid, reason in now_banned.iteritems():
                udata = self.ircd.users[uid]
                udata.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
                udata.disconnect("Z:Lined: {}".format(reason))
        else:
            del self.banList[data["mask"]]
            user.sendMessage("NOTICE", ":*** Z:Line removed on {}".format(data["mask"]))
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "ZLINE", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
            return {}
        banmask = params[0]
        if banmask in self.ircd.users:
            banmask = self.ircd.users[banmask].ip
        self.expire_zlines()
        if banmask[0] == "-":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
                return {}
            if banmask not in self.banList:
                user.sendMessage("NOTICE", ":*** Z:line on {} not found!  Check /stats Z for a list of active z:lines.".format(banmask))
                return {}
            return {
                "user": user,
                "mask": banmask
            }
        if len(params) < 3 or not params[2]:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
            return {}
        if banmask[0] == "+":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ZLINE", ":Not enough parameters")
                return {}
        if banmask in self.banList:
            user.sendMessage("NOTICE", ":*** There is already a z:line set on {}!  Check /stats Z for a list of active z:lines.".format(banmask))
            return {}
        return {
            "user": user,
            "mask": banmask,
            "duration": parse_duration(params[1]),
            "reason": " ".join(params[2:])
        }
    
    def stats_list(self, user, statsType):
        if statsType != "Z":
            return
        self.expire_zlines()
        for mask, linedata in self.banList.iteritems():
            user.sendMessage(irc.RPL_STATSZLINE, ":{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
    
    def check_connect(self, user):
        reason = self.match_zline(user)
        if not reason:
            return True
        user.sendMessage("NOTICE", ":{}".format(self.ircd.servconfig["client_ban_msg"]))
        user.sendMessage("ERROR", ":Closing Link: {} [Z:Lined: {}]".format(user.ip, reason), to=None, prefix=None)
        return False
    
    def match_zline(self, user):
        if "o" in user.mode:
            return None
        self.expire_zlines()
        for mask, linedata in self.banList.iteritems():
            if fnmatch(user.ip, mask):
                return linedata["reason"]
        return None
    
    def expire_zlines(self):
        current_time = epoch(now())
        expired = []
        for mask, linedata in self.banList.iteritems():
            if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
                expired.append(mask)
        for mask in expired:
            del self.banList[mask]

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.zlineCmd = None
    
    def spawn(self):
        self.zlineCmd = ZlineCommand()
        return {
            "commands": {
                "ZLINE": self.zlineCmd
            },
            "actions": {
                "statsoutput": [self.zlineCmd.stats_list],
                "connect": [self.zlineCmd.check_connect]
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["ZLINE"]
        self.ircd.actions["statsoutput"].remove(self.zlineCmd.stats_list)
        self.ircd.actions["connect"].remove(self.zlineCmd.check_connect)
    
    def data_serialize(self):
        return [self.zlineCmd.banList._data, {}]
    
    def data_unserialize(self, data):
        for mask, linedata in data.iteritems():
            self.zlineCmd.banList[mask] = linedata