from txircd.modbase import Mode

class OperMode(Mode):
    def checkSet(self, target, param):
        return False # Should only be set by the OPER command; hence, reject any normal setting of the mode
    
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
                "wholinemodify": [self.oper_mode.checkWhoFilter]
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("uno")
        self.ircd.actions["wholinemodify"].remove(self.oper_mode.checkWhoFilter)