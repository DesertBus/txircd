from twisted.words.protocols import irc
from txircd.modbase import Command, Mode

class WallopsCommand(Command):
    def onUse(self, user, data):
        if "message" in data:
            message = data["message"]
            for u in self.ircd.users.itervalues():
                if "w" in u.mode:
                    u.sendMessage("WALLOPS", ":{}".format(message), to=None, prefix=user.prefix())
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "WALLOPS", ":You have not registered")
            return {}
        if "o" not in user.mode:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command WALLOPS requires oper privileges")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "WALLOPS", ":Not enough parameters")
            return {}
        return {
            "user": user,
            "message": " ".join(params)
        }

class WallopsMode(Mode):
    pass # It's just a flag, settable or removable by the user

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "WALLOPS": WallopsCommand()
            },
            "modes": {
                "unw": WallopsMode()
            },
            "common": True
        }