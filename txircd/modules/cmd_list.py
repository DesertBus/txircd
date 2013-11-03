from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower
from fnmatch import fnmatch

class ListCommand(Command):
    def onUse(self, user, data):
        chancache = []
        for channame, channel in self.ircd.channels.iteritems():
            if data["chanfilter"] is not None:
                filterMatch = False
                for filterEntry in data["chanfilter"]:
                    if fnmatch(channame, filterEntry):
                        filterMatch = True
                        break
                if not filterMatch:
                    continue
            chancache.append({
                "channel": channel,
                "name": channel.name,
                "users": len(channel.users),
                "topic": channel.topic if channel.topic else ""
            })
        if "listdata" in self.ircd.actions:
            for action in self.ircd.actions["listdata"]:
                chancache = action(user, chancache)
                if not chancache:
                    break
        for cdata in chancache:
            user.sendMessage(irc.RPL_LIST, cdata["name"], str(cdata["users"]), ":[{}] {}".format(cdata["channel"].modeString(user), cdata["topic"]))
        user.sendMessage(irc.RPL_LISTEND, ":End of channel list")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "LIST", ":You have not registered")
            return {}
        if params:
            chanFilter = irc_lower(params[0]).split(",")
        else:
            chanFilter = None
        return {
            "user": user,
            "chanfilter": chanFilter
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "LIST": ListCommand()
            }
        }