from twisted.words.protocols import irc
from txircd.modbase import Command

class VersionCommand(Command):
    def onUse(self, user, data):
        user.sendMessage(irc.RPL_VERSION, ":{} {}".format(self.ircd.version, self.ircd.servconfig["server_name"]))
        user.send_isupport()

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "VERSION": VersionCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["VERSION"]