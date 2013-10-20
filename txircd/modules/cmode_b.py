from twisted.words.protocols import irc
from txircd.modbase import Mode
from txircd.utils import irc_lower, epoch, now, CaseInsensitiveDictionary
from fnmatch import fnmatch

class BanMode(Mode):
    def checkSet(self, user, target, param):
        if " " in param:
            param = param[:param.index(" ")]
        if "b" in target.mode and len(target.mode["b"]) >= self.ircd.servconfig["channel_ban_list_size"]:
            return [False, param]
        if "!" not in param and "@" not in param:
            param = "{}!*@*".format(param)
        elif "@" not in param:
            param = "{}@*".format(param)
        elif "!" not in param:
            param = "*!{}".format(param)
        if "bandata" not in target.cache:
            target.cache["bandata"] = {}
        target.cache["bandata"][param] = [user.nickname, epoch(now())]
        return [True, param]
    
    def checkUnset(self, user, target, param):
        if " " in param:
            param = param[:param.index(" ")]
        if "!" not in param and "@" not in param:
            param = "{}!*@*".format(param)
        elif "@" not in param:
            param = "{}@*".format(param)
        elif "!" not in param:
            param = "*!{}".format(param)
        for banmask in target.mode["b"]:
            if param == banmask:
                if "bandata" in target.cache and param in target.cache["bandata"]: # Just in case something happened, although bandata shouldn't just disappear
                    del target.cache["bandata"][param]
                return [True, param]
        return [False, param]
    
    def checkPermission(self, user, cmd, data):
        if cmd != "JOIN":
            return data
        channels = data["targetchan"]
        if "ban_evaluating" not in user.cache:
            user.cache["ban_evaluating"] = channels
            return "again"
        keys = data["keys"]
        for hostmask in (irc_lower(user.prefix()), irc_lower("{}!{}@{}".format(user.nickname, user.username, user.realhost)), irc_lower("{}!{}@{}".format(user.nickname, user.username, user.ip))):
            remove = []
            for chan in user.cache["ban_evaluating"]:
                if "b" in chan.mode:
                    for mask in chan.mode["b"]:
                        if fnmatch(hostmask, irc_lower(mask)):
                            remove.append(chan)
                            user.sendMessage(irc.ERR_BANNEDFROMCHAN, chan.name, ":Cannot join channel (You're banned)")
                            break
            for chan in remove:
                index = channels.index(chan)
                channels.pop(index)
                keys.pop(index)
        data["targetchan"] = channels
        data["keys"] = keys
        del user.cache["ban_evaluating"]
        return data
    
    def showParam(self, user, target):
        if "b" in target.mode:
            for entry in target.mode["b"]:
                metadata = target.cache["bandata"][entry] if "bandata" in target.cache and entry in target.cache["bandata"] else [ self.ircd.name, epoch(now()) ]
                user.sendMessage(irc.RPL_BANLIST, target.name, entry, metadata[0], str(metadata[1]))
            if "bandata" in target.cache:
                removeMask = []
                for mask in target.cache["bandata"]:
                    if mask not in target.mode["b"]:
                        removeMask.append(mask)
                for mask in removeMask:
                    del target.cache["bandata"][mask]
        elif "bandata" in target.cache:
            del target.cache["bandata"] # clear all saved ban data if no bans are set on channel
        user.sendMessage(irc.RPL_ENDOFBANLIST, target.name, ":End of channel ban list")

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.ban_mode = None
    
    def spawn(self):
        if "channel_ban_list_size" not in self.ircd.servconfig:
            self.ircd.servconfig["channel_ban_list_size"] = 60
        self.ban_mode = BanMode()
        return {
            "modes": {
                "clb": self.ban_mode
            },
            "common": True
        }