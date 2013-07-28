from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now, irc_lower, parse_duration, CaseInsensitiveDictionary
from fnmatch import fnmatch

irc.RPL_STATSSHUN = "223" # This use of this numeric doesn't normally have a name.

class ShunCommand(Command):
    def __init__(self):
        self.shunList = CaseInsensitiveDictionary()
    
    def onUse(self, user, data):
        if "reason" in data:
            self.shunList[data["mask"]] = {
                "setter": user.nickname,
                "created": epoch(now()),
                "duration": data["duration"],
                "reason": data["reason"]
            }
            user.sendMessage("NOTICE", ":*** Shun set on {}, to expire in {} seconds".format(data["mask"], data["duration"]))
        else:
            del self.shunList[data["mask"]]
            user.sendMessage("NOTICE", ":*** Shun removed on {}".format(data["mask"]))
        for udata in self.ircd.users.itervalues():
            if self.match_shun(udata):
                udata.cache["shunned"] = True
            else:
                udata.cache["shunned"] = False
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "SHUN", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
            return {}
        banmask = params[0]
        if banmask in self.ircd.users:
            udata = self.ircd.users[banmask]
            banmask = "{}@{}".format(udata.username, udata.hostname)
        elif "@" not in banmask:
            banmask = "*@{}".format(banmask)
        self.expire_shuns()
        if banmask[0] == "-":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
                return {}
            if banmask not in self.shunList:
                user.sendMessage("NOTICE", ":*** Shun {} not found; check /stats S for a list of active shuns.".format(banmask))
                return {}
            return {
                "user": user,
                "mask": banmask
            }
        if len(params) < 3 or not params[2]:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
            return {}
        if banmask[0] == "+":
            banmask = banmask[1:]
            if not banmask:
                user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SHUN", ":Not enough parameters")
                return {}
        if banmask in self.shunList:
            user.sendMessage("NOTICE", ":*** Shun {} is already set!  Check /stats S for a list of active shuns.".format(banmask))
            return {}
        return {
            "user": user,
            "mask": banmask,
            "duration": parse_duration(params[1]),
            "reason": " ".join(params[2:])
        }
    
    def statsList(self, user, statsType):
        if statsType != "S":
            return
        self.expire_shuns()
        for mask, linedata in self.shunList.iteritems():
            user.sendMessage(irc.RPL_STATSSHUN, "{} {} {} {} :{}".format(mask, linedata["created"], linedata["duration"], linedata["setter"], linedata["reason"]))
    
    def check_register(self, user):
        reason = self.match_shun(user)
        if reason:
            user.cache["shunned"] = True
        elif reason == None:
            user.cache["shunned"] = False
        else:
            return "again"
        return True
    
    def reassign_shun(self, user):
        reason = self.match_shun(user)
        if reason:
            user.cache["shunned"] = True
        else:
            user.cache["shunned"] = False
        return None # the xline_rematch hook shouldn't automatically operate on these, so let's make it not.
    
    def match_shun(self, user):
        self.expire_shuns()
        if "except_line" in user.cache:
            if user.cache["except_line"]:
                return None
            matchMask = "{}@{}".format(user.username, user.hostname)
            for mask, linedata in self.shunList.iteritems():
                if fnmatch(matchMask, mask):
                    return linedata["reason"]
            matchMask = "{}@{}".format(user.username, user.ip)
            for mask, linedata in self.shunList.iteritems():
                if fnmatch(matchMask, mask):
                    return linedata["reason"]
            return None
        elif "shunned" in user.cache:
            if user.cache["shunned"]:
                return "Shunned"
            return None
        else:
            matchMask = "{}@{}".format(user.username, user.hostname)
            for mask in self.shunList.iterkeys():
                if fnmatch(matchMask, mask):
                    user.cache["shunned"] = True
                    return ""
            matchMask = "{}@{}".format(user.username, user.ip)
            for mask in self.shunList.iterkeys():
                if fnmatch(matchMask, mask):
                    user.cache["shunned"] = True
                    return ""
            user.cache["shunned"] = False
            return None
    
    def expire_shuns(self):
        current_time = epoch(now())
        expired = []
        for mask, linedata in self.shunList.iteritems():
            if linedata["duration"] and current_time > linedata["created"] + linedata["duration"]:
                expired.append(mask)
        for mask in expired:
            del self.shunList[mask]
    
    def check_command(self, user, command, data):
        if "shunned" not in user.cache or not user.cache["shunned"]:
            return data
        if command not in self.ircd.servconfig["shun_command_list"]:
            return {}
        return data

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.shunCmd = None
    
    def spawn(self):
        if "shun_command_list" not in self.ircd.servconfig:
            self.ircd.servconfig["shun_command_list"] = ["JOIN", "PART", "QUIT", "PING", "PONG"]
        self.shunCmd = ShunCommand()
        return {
            "commands": {
                "SHUN": self.shunCmd
            },
            "actions": {
                "statsoutput": [self.shunCmd.statsList],
                "register": [self.shunCmd.check_register],
                "commandpermission": [self.shunCmd.check_command],
                "xline_rematch": [self.shunCmd.reassign_shun]
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["SHUN"]
        self.ircd.actions["statsoutput"].remove(self.shunCmd.statsList)
        self.ircd.actions["register"].remove(self.shunCmd.check_register)
        self.ircd.actions["commandpermission"].remove(self.shunCmd.check_command)
        self.ircd.actions["xline_rematch"].remove(self.shunCmd.reassign_shun)
    
    def data_serialize(self):
        return [self.shunCmd.shunList._data, {}]
    
    def data_unserialize(self, data):
        for mask, meta in data.iteritems():
            self.shunCmd.shunList[mask] = meta