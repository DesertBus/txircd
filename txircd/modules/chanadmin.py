from txircd.modbase import Mode

class AdminMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "csa&150": AdminMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("csa")