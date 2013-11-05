from twisted.words.protocols import irc
from txircd.modbase import Mode

class OperMode(Mode):
    def checkSet(self, user, target, param):
        user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - User mode o may not be set")
        return [False, param]# Should only be set by the OPER command; hence, reject any normal setting of the mode
    
    def checkWhoFilter(self, user, targetUser, filters, fields, channel, udata):
        if "o" in filters and not udata["oper"]:
            return {}
        return udata

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.oper_mode = None
    
    def spawn(self):
        self.oper_mode = OperMode()
        return {
            "modes": {
                "uno": self.oper_mode
            },
            "actions": {
                "wholinemodify": self.oper_mode.checkWhoFilter
            },
            "common": True
        }