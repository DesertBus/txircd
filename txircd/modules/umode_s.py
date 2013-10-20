from twisted.words.protocols import irc
from txircd.modbase import Mode
from txircd.utils import epoch, irc_lower, now

irc.RPL_LISTMODE = "728" # I made both of these up.  They're based on freenode's quiet lists,
irc.RPL_ENDOFLISTMODE = "729" # which have a parameter for the mode being queried.

class ServerNoticeMode(Mode):
    tellLists = {}
    
    def checkSet(self, user, target, param):
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Only operators may set user mode s")
            return [False, param]
        mask = irc_lower(param)
        if mask not in self.tellLists:
            self.tellLists[mask] = []
        self.tellLists[mask].append(target)
        if "servernoticedata" not in target.cache:
            target.cache["servernoticedata"] = {}
        target.cache["servernoticedata"][mask] = epoch(now())
        return [True, mask]
    
    def checkUnset(self, user, target, param):
        mask = irc_lower(param)
        if mask in self.tellLists and target in self.tellLists[mask]:
            self.tellLists[mask].remove(target)
        if "servernoticedata" in target.cache and mask in target.cache["servernoticedata"]:
            del target.cache["servernoticedata"][mask]
        return [True, mask]
    
    def showParam(self, user, target):
        if "s" in target.mode:
            for mask in target.mode["s"]:
                time = target.cache["servernoticedata"][mask] if "servernoticedata" in target.cache and mask in target.cache["servernoticedata"] else epoch(now())
                user.sendMessage(irc.RPL_LISTMODE, target.nickname, "s", mask, target.nickname, str(time))
        user.sendMessage(irc.RPL_ENDOFLISTMODE, target.nickname, "s", ":End of server notice type list")
    
    def sendServerNotice(self, type, message):
        type = irc_lower(type)
        if type in self.tellLists:
            for u in self.tellLists[type]:
                u.sendMessage("NOTICE", ":*** {}: {}".format(type.upper(), message))

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.servernotice = None
    
    def spawn(self):
        self.servernotice = ServerNoticeMode()
        self.ircd.module_data_cache["sendservernotice"] = self.servernotice.sendServerNotice
        return {
            "modes": {
                "uls": self.servernotice
            },
            "common": True
        }
    
    def cleanup(self):
        del self.ircd.module_data_cache["sendservernotice"]
    
    def data_serialize(self):
        return [{}, { "telllists": self.servernotice.tellLists }]
    
    def data_unserialize(self, data):
        if "telllists" in data:
            self.servernotice.tellLists = data["telllists"]