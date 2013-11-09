from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import CaseInsensitiveDictionary, now, epoch, parse_duration

class WhowasCommand(Command):
    def __init__(self):
        self.history = CaseInsensitiveDictionary()
    
    def onUse(self, user, data):
        if "nicks" not in data:
            return
        for oldNick in data["nicks"]:
            if oldNick not in self.history:
                user.sendMessage(irc.ERR_WASNOSUCHNICK, oldNick, ":No such nick")
                user.sendMessage(irc.RPL_ENDOFWHOWAS, oldNick, ":End of /WHOWAS list")
                continue
            historyList = self.history[oldNick]
            for entry in historyList:
                user.sendMessage(irc.RPL_WHOWASUSER, entry["nick"], entry["ident"], entry["host"], "*", ":{}".format(entry["gecos"]))
                user.sendMessage(irc.RPL_WHOISSERVER, entry["nick"], entry["server"], ":{}".format(entry["time"]))
            user.sendMessage(irc.RPL_ENDOFWHOWAS, oldNick, ":End of /WHOWAS list")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "WHOWAS", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
            return {}
        users = params[0].split(",")
        if len(params) >= 2:
            count = None
            hostType = None
            if params[1].isdigit():
                count = int(params[1])
            elif "o" in user.mode:
                hostType = params[1].lower()
            if len(params) >= 3 and hostType is None and "o" in user.mode:
                hostType = params[2].lower()
            if hostType not in ("realhost", "ip"):
                hostType = None
            if count and count > 0 and hostType:
                return {
                    "user": user,
                    "nicks": users,
                    "count": count,
                    "hosttype": hostType
                }
            elif hostType:
                return {
                    "user": user,
                    "nicks": users,
                    "hosttype": hostType
                }
            elif count and count > 0:
                return {
                    "user": user,
                    "nicks": users,
                    "count": count
                }
        return {
            "user": user,
            "nicks": users
        }
    
    def addToWhowas(self, user, reason):
        if user.registered > 0:
            return # don't process users who haven't yet registered
        newEntry = {
            "nick": user.nickname,
            "ident": user.username,
            "host": user.hostname,
            "realhost": user.realhost,
            "ip": user.ip,
            "gecos": user.realname,
            "server": user.server,
            "time": now()
        }
        if user.nickname in self.history:
            self.history[user.nickname].append(newEntry)
            self.history[user.nickname] = self.history[user.nickname][-self.ircd.servconfig["client_whowas_limit"]:]
            expiryTime = epoch(now()) - parse_duration(self.ircd.servconfig["client_whowas_expire"])
            while epoch(self.history[user.nickname][0]["time"]) < expiryTime:
                self.history[user.nickname].pop(0)
        else:
            self.history[user.nickname] = [newEntry]

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.whowasCmd = None
    
    def spawn(self):
        if "client_whowas_limit" not in self.ircd.servconfig:
            self.ircd.servconfig["client_whowas_limit"] = 10
        if "client_whowas_expire" not in self.ircd.servconfig:
            self.ircd.servconfig["client_whowas_expire"] = "1d"
        self.whowasCmd = WhowasCommand()
        return {
            "commands": {
                "WHOWAS": self.whowasCmd
            },
            "actions": {
                "quit": self.whowasCmd.addToWhowas
            }
        }
    
    def data_serialize(self):
        expiryTime = epoch(now()) - parse_duration(self.ircd.servconfig["client_whowas_expire"])
        remove = []
        for nick, data in self.whowasCmd.history.iteritems():
            while data and epoch(data[0]["time"]) < expiryTime:
                data.pop(0)
            if not data:
                remove.append(nick)
        for nick in remove:
            del self.whowasCmd.history[nick]
        return [self.whowasCmd.history._data, {}]
    
    def data_unserialize(self, data):
        for nick, entries in data.iteritems():
            # UPGRADE BEGIN
            # 0.2.6: The following code upgrades data from 0.2.5 or prior
            for entry in entries:
                if "realhost" not in entry:
                    entry["realhost"] = entry["host"]
                if "ip" not in entry:
                    entry["ip"] = "0.0.0.0"
            # UPGRADE END
            self.whowasCmd.history[nick] = entries
