from txircd.modbase import Module

class QuitServerNotice(Module):
    def sendQuitNotice(self, user, reason):
        if "sendservernotice" in self.ircd.module_data_cache:
            message = "Client quit: {} ({}) [{}]".format(user.prefix(), user.ip, reason)
            self.ircd.module_data_cache["sendservernotice"]("quit", message)

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.quitnotice = None
    
    def spawn(self):
        self.quitnotice = QuitServerNotice().hook(self.ircd)
        return {
            "actions": {
                "quit": self.quitnotice.sendQuitNotice
            }
        }