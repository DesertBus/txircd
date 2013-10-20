from txircd.channel import IRCChannel
from txircd.modbase import Module

class Autojoin(Module):
    def joinOnConnect(self, user):
        if "client_join_on_connect" in self.ircd.servconfig:
            for channel in self.ircd.servconfig["client_join_on_connect"]:
                user.handleCommand("JOIN", None, [channel])
        return True

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.conn_join = None
    
    def spawn(self):
        self.conn_join = Autojoin().hook(self.ircd)
        return {
            "actions": {
                "welcome": self.conn_join.joinOnConnect
            }
        }