from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import chunk_message, irc_lower

# These numerics are as stated in the IRCv3 MONITOR specification: http://ircv3.atheme.org/specification/monitor-3.2
irc.RPL_MONONLINE = "730"
irc.RPL_MONOFFLINE = "731"
irc.RPL_MONLIST = "732"
irc.RPL_ENDOFMONLIST = "733"
irc.ERR_MONLISTFULL = "734"

class MonitorCommand(Command):
    def __init__(self, limit):
        self.limit = limit
    
    def onUse(self, user, data):
        modifier = data["modifier"]
        if modifier == "+":
            targetlist = data["targetlist"]
            discard = []
            for target in targetlist:
                if len(target) > 32 or " " in target:
                    discard.append(target)
            for target in discard:
                targetlist.remove(target)
            if "monitormasks" not in user.cache:
                user.cache["monitormasks"] = []
            if "monitorwatching" not in user.cache:
                user.cache["monitorwatching"] = []
            if self.limit and len(user.cache["monitormasks"]) + len(targetlist) > self.limit:
                user.sendMessage(irc.ERR_MONLISTFULL, str(self.limit), ",".join(targetlist), ":Monitor list is full")
                return
            online = []
            offline = []
            for target in targetlist:
                lowerTarget = irc_lower(target)
                if lowerTarget not in user.cache["monitorwatching"]:
                    user.cache["monitormasks"].append(target)
                    user.cache["monitorwatching"].append(lowerTarget)
                    if lowerTarget not in self.ircd.module_data_cache["monitorwatchedby"]:
                        self.ircd.module_data_cache["monitorwatchedby"][lowerTarget] = []
                    self.ircd.module_data_cache["monitorwatchedby"][lowerTarget].append(user)
                if target in self.ircd.users:
                    online.append(target)
                else:
                    offline.append(target)
            if online:
                onLines = chunk_message(" ".join(online), 400)
                for line in onLines:
                    user.sendMessage(irc.RPL_MONONLINE, ":{}".format(line.replace(" ", ",")))
            if offline:
                offLines = chunk_message(" ".join(offline), 400)
                for line in offLines:
                    user.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(line.replace(" ", ",")))
        elif modifier == "-":
            targetlist = data["targetlist"]
            if "monitormasks" not in user.cache or "monitorwatching" not in user.cache:
                return
            for target in targetlist:
                lowerTarget = irc_lower(target)
                if lowerTarget in user.cache["monitorwatching"]:
                    user.cache["monitorwatching"].remove(lowerTarget)
                    watchList = user.cache["monitormasks"]
                    for mask in watchList:
                        if irc_lower(mask) == lowerTarget:
                            user.cache["monitormasks"].remove(mask)
                if lowerTarget in self.ircd.module_data_cache["monitorwatchedby"]:
                    self.ircd.module_data_cache["monitorwatchedby"][lowerTarget].remove(user)
        elif modifier == "C":
            if "monitormasks" in user.cache:
                del user.cache["monitormasks"]
            if "monitorwatching" in user.cache:
                for target in user.cache["monitorwatching"]:
                    self.ircd.module_data_cache["monitorwatchedby"][target].remove(user)
                del user.cache["monitorwatching"]
        elif modifier == "L":
            if "monitormasks" in user.cache:
                userlist = chunk_message(" ".join(user.cache["monitormasks"]), 400)
                for line in userlist:
                    user.sendMessage(irc.RPL_MONLIST, ":{}".format(line.replace(" ", ",")))
            user.sendMessage(irc.RPL_ENDOFMONLIST, ":End of MONITOR list")
        elif modifier == "S":
            if "monitormasks" in user.cache:
                online = []
                offline = []
                for target in user.cache["monitormasks"]:
                    if target in self.ircd.users:
                        online.append(target)
                    else:
                        offline.append(target)
                if online:
                    onlineLines = chunk_message(" ".join(online), 400)
                    for line in onlineLines:
                        user.sendMessage(irc.RPL_MONONLINE, ":{}".format(line.replace(" ", ",")))
                if offline:
                    offlineLines = chunk_message(" ".join(offline), 400)
                    for line in offlineLines:
                        user.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(line.replace(" ", ",")))
    
    def processParams(self, user, params):
        if not params:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "MONITOR", ":Not enough parameters")
            return {}
        if params[0] in ["C", "L", "S"]:
            return {
                "user": user,
                "modifier": params[0]
            }
        if params[0] in ["+", "-"]:
            return {
                "user": user,
                "modifier": params[0],
                "targetlist": params[1].split(",")
            }
        return {}
    
    def notifyConnect(self, user):
        lowerNick = irc_lower(user.nickname)
        watchedBy = self.ircd.module_data_cache["monitorwatchedby"]
        if lowerNick in watchedBy:
            for watcher in watchedBy[lowerNick]:
                watcher.sendMessage(irc.RPL_MONONLINE, ":{}".format(user.nickname))
        return True
    
    def notifyQuit(self, user, reason):
        watchedBy = self.ircd.module_data_cache["monitorwatchedby"]
        if user.registered == 0:
            lowerNick = irc_lower(user.nickname)
            if lowerNick in watchedBy:
                for watcher in watchedBy[lowerNick]:
                    watcher.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(user.nickname))
    
    def notifyNick(self, user, oldNick):
        lowerNick = irc_lower(user.nickname)
        lowerOldNick = irc_lower(oldNick)
        watchedBy = self.ircd.module_data_cache["monitorwatchedby"]
        if lowerOldNick in watchedBy:
            for watcher in watchedBy[lowerOldNick]:
                watcher.sendMessage(irc.RPL_MONOFFLINE, ":{}".format(oldNick))
        if lowerNick in watchedBy:
            for watcher in watchedBy[lowerNick]:
                watcher.sendMessage(irc.RPL_MONONLINE, ":{}".format(user.nickname))

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.monitor_cmd = None
    
    def spawn(self):
        if "client_monitor_limit" not in self.ircd.servconfig:
            self.ircd.servconfig["client_monitor_limit"] = None # Default to no limit
        try:
            mon_limit = int(self.ircd.servconfig["client_monitor_limit"])
        except TypeError:
            mon_limit = None # When we do not enforce a limit, we don't show a value for MONITOR in ISUPPORT; the ISUPPORT code hides values of None
        except ValueError:
            mon_limit = None # Invalid arguments go to the default
        self.ircd.isupport["MONITOR"] = mon_limit
        self.monitor_cmd = MonitorCommand(mon_limit)
        self.ircd.module_data_cache["monitorwatchedby"] = {}
        return {
            "commands": {
                "MONITOR": self.monitor_cmd
            },
            "actions": {
                "register": self.monitor_cmd.notifyConnect,
                "quit": self.monitor_cmd.notifyQuit,
                "nick": self.monitor_cmd.notifyNick
            }
        }
    
    def cleanup(self):
        del self.ircd.isupport["MONITOR"]