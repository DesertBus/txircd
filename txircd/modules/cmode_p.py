from txircd.modbase import Mode

class PrivateMode(Mode):
    def listOutput(self, user, chanlist):
        for cdata in chanlist:
            if "p" in cdata["channel"].mode and user not in cdata["channel"].users:
                cdata["name"] = "*"
                cdata["topic"] = ""
        return chanlist
    # other +p stuff is in other modules

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.mode_p = None
    
    def spawn(self):
        self.mode_p = PrivateMode()
        return {
            "modes": {
                "cnp": self.mode_p
            },
            "actions": {
                "listdata": self.mode_p.listOutput
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("cnp")
        self.ircd.actions["listdata"].remove(self.mode_p.listOutput)