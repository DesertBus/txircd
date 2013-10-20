from txircd.modbase import Module

class ConnectServerNotice(Module):
    def sendConnectNotice(self, user):
        if "sendservernotice" in self.ircd.module_data_cache:
            message = "Client connected on {}: {} ({}) [{}]".format(user.server, user.prefix(), user.ip, user.realname)
            self.ircd.module_data_cache["sendservernotice"]("connect", message)
        return True

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.connectNotice = None
    
    def spawn(self):
        self.connectNotice = ConnectServerNotice().hook(self.ircd)
        return {
            "actions": {
                "register": self.connectNotice.sendConnectNotice
            }
        }