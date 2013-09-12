from txircd.modbase import Mode

class HalfopMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "csh%50": HalfopMode()
            },
            "common": True
        }