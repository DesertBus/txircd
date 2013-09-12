from twisted.words.protocols import irc
from txircd.modbase import Module

irc.RPL_WHOSPCRPL = "354"

class WhoX(Module):
    def whox(self, user, targetUser, filters, fields, channel, udata):
        if not fields:
            return False
        responses = []
        if "c" in fields:
            responses.append(udata["channel"])
        if "u" in fields:
            responses.append(udata["ident"])
        if "i" in fields:
            if "o" in user.mode:
                responses.append(udata["ip"])
            else:
                responses.append("0.0.0.0")
        if "h" in fields:
            responses.append(udata["host"])
        if "s" in fields:
            responses.append(udata["server"])
        if "n" in fields:
            responses.append(udata["nick"])
        if "f" in fields:
            responses.append("{}{}{}".format("G" if udata["away"] else "H", "*" if udata["oper"] else "", udata["status"]))
        if "d" in fields:
            responses.append(str(udata["hopcount"]))
        if "l" in fields:
            responses.append(str(udata["idle"]))
        if "a" in fields:
            responses.append(udata["account"])
        if "r" in fields:
            responses.append(":{}".format(udata["gecos"]))
        user.sendMessage(irc.RPL_WHOSPCRPL, *responses)
        return True

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.whox = None
    
    def spawn(self):
        self.whox = WhoX().hook(self.ircd)
        return {
            "actions": {
                "wholinedisplay": self.whox.whox
            }
        }
    
    def cleanup(self):
        self.ircd.actions["wholinedisplay"].remove(self.whox.whox)