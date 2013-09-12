from twisted.words.protocols import irc
from txircd.modbase import Mode

class OpMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "cso@100": OpMode()
            },
            "common": True
        }