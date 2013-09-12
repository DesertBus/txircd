from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, irc_lower, now
from fnmatch import fnmatch

class WhoCommand(Command):
    def onUse(self, user, data):
        if "target" not in data:
            for u in self.ircd.users.itervalues():
                if "i" in u.mode:
                    continue
                common_channel = False
                for chan in self.ircd.channels.itervalues():
                    if user in chan.users and u in chan.users:
                        common_channel = True
                        break
                if not common_channel:
                    self.sendWhoLine(user, u, "*", None, data["filters"] if "filters" in data else "", data["fields"] if "fields" in data else "")
            user.sendMessage(irc.RPL_ENDOFWHO, "*", ":End of /WHO list.")
        else:
            if data["target"] in self.ircd.channels:
                cdata = self.ircd.channels[data["target"]]
                in_channel = user in cdata.users # cache this value instead of searching every iteration
                if not in_channel and ("p" in cdata.mode or "s" in cdata.mode):
                    irc.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
                    return
                for u in cdata.users.iterkeys():
                    self.sendWhoLine(user, u, cdata.name, cdata, data["filters"], data["fields"])
                user.sendMessage(irc.RPL_ENDOFWHO, cdata.name, ":End of /WHO list.")
            else:
                for u in self.ircd.users.itervalues():
                    if fnmatch(irc_lower(u.nickname), irc_lower(data["target"])) or fnmatch(irc_lower(u.hostname), irc_lower(data["target"])):
                        self.sendWhoLine(user, u, data["target"], None, data["filters"], data["fields"])
                user.sendMessage(irc.RPL_ENDOFWHO, data["target"], ":End of /WHO list.") # params[0] is used here for the target so that the original glob pattern is returned
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "WHO", ":You have not registered")
            return {}
        if not params:
            return {
                "user": user
            }
        target = params[0]
        filters = params[1] if len(params) > 1 else ""
        if "%" in filters:
            filters, fields = filters.split("%", 1)
        else:
            fields = ""
        if target[0][0] == "#" and target not in self.ircd.channels:
            user.sendMessage(irc.RPL_ENDOFWHO, channel, ":End of /WHO list")
            return {}
        return {
            "user": user,
            "target": target,
            "filters": filters,
            "fields": fields
        }
    
    def sendWhoLine(self, user, targetUser, destination, channel, filters, fields):
        displayChannel = destination
        if not channel:
            for chan in self.ircd.channels.itervalues():
                if user in chan.users and targetUser in chan.users:
                    displayChannel = chan
                    break
            else:
                displayChannel = "*"
        udata = {
            "dest": destination,
            "nick": targetUser.nickname,
            "ident": targetUser.username,
            "host": targetUser.hostname,
            "ip": targetUser.ip,
            "server": targetUser.server,
            "away": "away" in targetUser.metadata["ext"],
            "oper": "o" in targetUser.mode,
            "idle": epoch(now()) - epoch(targetUser.lastactivity),
            "status": self.ircd.prefixes[channel.users[targetUser][0]][0] if channel and channel.users[targetUser] else "",
            "hopcount": 0,
            "gecos": targetUser.realname,
            "account": targetUser.metadata["ext"]["accountname"] if "accountname" in targetUser.metadata["ext"] else "0",
            "channel": displayChannel
        }
        if "wholinemodify" in self.ircd.actions:
            tryagain = []
            for action in self.ircd.actions["wholinemodify"]:
                newdata = action(user, targetUser, filters, fields, channel, udata)
                if newdata == "again":
                    tryagain.append(action)
                elif not newdata:
                    return
                udata = newdata
            for action in tryagain:
                udata = action(user, targetUser, filters, fields, channel, udata)
                if not udata:
                    return
        if "wholinedisplay" in self.ircd.actions:
            for action in self.ircd.actions["wholinedisplay"]:
                handled = action(user, targetUser, filters, fields, channel, udata)
                if handled:
                    return
        user.sendMessage(irc.RPL_WHOREPLY, udata["dest"], udata["ident"], udata["host"], udata["server"], udata["nick"], "{}{}{}".format("G" if udata["away"] else "H", "*" if udata["oper"] else "", udata["status"]), ":{} {}".format(udata["hopcount"], udata["gecos"]))

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "WHO": WhoCommand()
            }
        }