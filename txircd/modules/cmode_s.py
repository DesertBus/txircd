from twisted.words.protocols import irc
from txircd.modbase import Mode

class SecretMode(Mode):
    def checkPermission(self, user, cmd, data):
        if cmd != "NAMES":
            return data
        remove = []
        for chan in data["targetchan"]:
            if "s" in chan.mode and chan.name not in user.channels:
                user.sendMessage(irc.ERR_NOSUCHNICK, chan, ":No such nick/channel")
                remove.append(chan)
        for chan in remove:
            data["targetchan"].remove(chan)
        return data
    
    def listOutput(self, command, data):
        if command != "LIST":
            return data
        if "cdata" not in data:
            return data
        cdata = data["cdata"]
        if "s" in cdata["channel"].mode and cdata["channel"].name not in data["user"].channels:
            data["cdata"].clear()
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
                "commandextra": [self.mode_s.listOutput]
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("cns")
        self.ircd.actions["commandextra"].remove(self.mode_s.listOutput)