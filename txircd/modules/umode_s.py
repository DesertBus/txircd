from txircd.modbase import Mode

class ServerNoticeMode(Mode):
    pass

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "uns": ServerNoticeMode()
            },
            "common": True
        }
    
    def cleanup(self):
        self.ircd.removeMode("uns")