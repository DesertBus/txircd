from twisted.words.protocols import irc
from txircd.modbase import Command

class LinksCommand(Command):
    def onUse(self, user, data):
        for servname, data in self.ircd.servers.iteritems():
            user.sendMessage(irc.RPL_LINKS, servname, data.nearHop, ":{} {}".format(data.hopCount, data.description))
        user.sendMessage(irc.RPL_LINKS, self.ircd.name, self.ircd.name, ":0 {}".format(self.ircd.servconfig["server_description"]))
        user.sendMessage(irc.RPL_ENDOFLINKS, "*", ":End of /LINKS list.")

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "LINKS": LinksCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["LINKS"]