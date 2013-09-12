from txircd.modbase import Mode

class VoiceMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "csv+10": VoiceMode()
            },
            "common": True
        }