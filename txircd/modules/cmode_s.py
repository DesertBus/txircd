from twisted.words.protocols import irc
from txircd.modbase import Mode

class SecretMode(Mode):
    def checkPermission(self, user, cmd, data):
        if cmd != "NAMES":
            return data
        remove = []
        for chan in data["targetchan"]:
            if "s" in chan.mode and user not in chan.users:
                user.sendMessage(irc.ERR_NOSUCHNICK, chan, ":No such nick/channel")
                remove.append(chan)
        for chan in remove:
            data["targetchan"].remove(chan)
        return data
    
    def listOutput(self, user, chanlist):
        remove = []
        for cdata in chanlist:
            if "s" in cdata["channel"].mode and user not in cdata["channel"].users:
                remove.append(cdata)
        for item in remove:
            chanlist.remove(item)
        return chanlist
    # other +s stuff is hiding in other modules.

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.mode_s = None
    
    def spawn(self):
        self.mode_s = SecretMode()
        return {
            "modes": {
                "cns": self.mode_s
            },
            "actions": {
                "listdata": self.mode_s.listOutput
            },
            "common": True
        }