from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now

irc.RPL_WHOISACCOUNT = "330"
irc.RPL_WHOISSECURE  = "671"
irc.RPL_WHOISCERTFP = "276"
irc.RPL_WHOISHOST = "378"

class WhoisCommand(Command):
    def onUse(self, user, data):
        if "targetuser" not in data:
            return
        targets = data["targetuser"]
        for u in targets:
            user.sendMessage(irc.RPL_WHOISUSER, u.nickname, u.username, u.hostname, "*", ":{}".format(u.realname))
            if "o" in user.mode or user == u:
                user.sendMessage(irc.RPL_WHOISHOST, u.nickname, ":is connecting from {}@{} {}".format(u.username, u.realhost, u.ip))
            chanlist = []
            for chan in self.ircd.channels.itervalues():
                if u in chan.users:
                    chanlist.append(chan)
            chandisplay = []
            for cdata in chanlist:
                if user in cdata.users or ("s" not in cdata.mode and "p" not in cdata.mode):
                    statuses = cdata.users[u] if u in cdata.users else ""
                    status = self.ircd.prefixes[statuses[0]][0] if statuses else ""
                    chandisplay.append("{}{}".format(status, cdata.name))
            if chandisplay:
                user.sendMessage(irc.RPL_WHOISCHANNELS, u.nickname, ":{}".format(" ".join(chandisplay)))
            user.sendMessage(irc.RPL_WHOISSERVER, u.nickname, u.server, ":{}".format(self.ircd.servconfig["server_description"] if u.server == self.ircd.name else self.ircd.servers[u.server].description))
            if "accountname" in u.metadata["ext"]:
                user.sendMessage(irc.RPL_WHOISACCOUNT, u.nickname, u.metadata["ext"]["accountname"], ":is logged in as")
            if u.socket.secure:
                user.sendMessage(irc.RPL_WHOISSECURE, u.nickname, ":is using a secure connection")
                if "certfp" in u.metadata["server"]:
                    user.sendMessage(irc.RPL_WHOISCERTFP, u.nickname, ":has client certificate fingerprint {}".format(u.metadata["server"]["certfp"]))
            if "o" in u.mode:
                user.sendMessage(irc.RPL_WHOISOPERATOR, u.nickname, ":is an IRC operator")
            if "whoisdata" in self.ircd.actions:
                for action in self.ircd.actions["whoisdata"]:
                    action(user, u)
            user.sendMessage(irc.RPL_WHOISIDLE, u.nickname, str(epoch(now()) - epoch(u.lastactivity)), str(epoch(u.signon)), ":seconds idle, signon time")
            user.sendMessage(irc.RPL_ENDOFWHOIS, u.nickname, ":End of /WHOIS list")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTREGISTERED, "WHOIS", ":You have not registered")
            return {}
        if not params:
            user.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
            return {}
        users = params[0].split(",")
        targets = []
        for u in users:
            if u not in self.ircd.users:
                user.sendMessage(irc.ERR_NOSUCHNICK, u, ":No such nick/channel")
                continue
            targets.append(self.ircd.users[u])
        if not targets:
            user.sendMessage(irc.RPL_ENDOFWHOIS, "*", ":End of /WHOIS list")
            return {}
        return {
            "user": user,
            "targetuser": targets
        }

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "commands": {
                "WHOIS": WhoisCommand()
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["WHOIS"]