from txircd.modbase import Mode

class OwnerMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "csq~200": OwnerMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("csq")