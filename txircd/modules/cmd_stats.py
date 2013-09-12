from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.server import ModuleMessage
from txircd.utils import epoch, now
import collections

irc.RPL_STATS = "210"
irc.RPL_STATSOPERS = "249"
irc.RPL_STATSPORTS = "249"

class StatsCommand(Command):
    def onUse(self, user, data):
        if "server" in data:
            data["server"].callRemote(ModuleMessage, destserver=data["server"].name, type="StatsRequest", args=[user.uuid, data["statstype"]])
            data["statstype"] = "" # supress the commandextra hook response
        else:
            for action in self.ircd.actions["statsoutput"]:
                action(user, data["statstype"])
            user.sendMessage(irc.RPL_ENDOFSTATS, data["statstype"], ":End of /STATS report")
    
    def processParams(self, user, params):
        if user.registered > 0:
            user.sendMessage(irc.ERR_NOTYETREGISTERED, "STATS", ":You have not registered")
            return {}
        if not params or not params[0]:
            user.sendMessage(irc.ERR_NEEDMOREPARAMS, "STATS", ":Not enough parameters")
            return {}
        statschar = params[0][0]
        if "o" not in user.mode and statschar not in self.ircd.servconfig["server_stats_public"]:
            user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - Stats {} requires operator privileges".format(statschar))
            return {}
        if len(params) == 1:
            return {
                "user": user,
                "statstype": statschar
            }
        if params[1] not in self.ircd.servers:
            user.sendMessage(irc.ERR_NOSUCHSERVER, params[1], ":No such server")
            return {}
        return {
            "user": user,
            "statstype": statschar,
            "server": self.ircd.servers[params[1]]
        }
    
    def statsChars(self, user, statschar):
        if statschar == "o":
            for user in self.ircd.users.itervalues():
                if "o" in user.mode:
                    user.sendMessage(irc.RPL_STATSOPERS, ":{} ({}@{}) Idle: {} secs".format(user.nickname, user.username, user.hostname, epoch(now()) - epoch(user.lastactivity)))
        elif statschar == "p":
            if isinstance(self.ircd.servconfig["server_port_tcp"], collections.Sequence):
                for port in self.ircd.servconfig["server_port_tcp"]:
                    user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(port))
            else:
                user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(self.ircd.servconfig["server_port_tcp"]))
            if isinstance(self.ircd.servconfig["server_port_ssl"], collections.Sequence):
                for port in self.ircd.servconfig["server_port_ssl"]:
                    user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(port))
            else:
                user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(self.ircd.servconfig["server_port_ssl"]))
            if isinstance(self.ircd.servconfig["server_port_web"], collections.Sequence):
                for port in self.ircd.servconfig["server_port_web"]:
                    user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(port))
            else:
                user.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(self.ircd.servconfig["server_port_web"]))
            if isinstance(self.ircd.servconfig["serverlink_port_tcp"], collections.Sequence):
                for port in self.ircd.servconfig["serverlink_port_tcp"]:
                    user.sendMessage(irc.RPL_STATSPORTS, ":{} (servers, plaintext)".format(port))
            else:
                user.sendMessage(irc.RPL_STATSPORTS, ":{} (servers, plaintext)".format(self.ircd.servconfig["serverlink_port_tcp"]))
            if isinstance(self.ircd.servconfig["serverlink_port_ssl"], collections.Sequence):
                for port in self.ircd.servconfig["serverlink_port_ssl"]:
                    user.sendMessage(irc.RPL_STATSPORTS, ":{} (servers, ssl)".format(port))
            else:
                user.sendMessage(irc.RPL_STATSPORTS, ":{} (servers, ssl)".format(self.ircd.servconfig["serverlink_port_ssl"]))
        elif statschar == "u":
            uptime = now() - self.ircd.created
            user.sendMessage(irc.RPL_STATSUPTIME, ":Server up {}".format(uptime if uptime.days > 0 else "0 days, {}".format(uptime)))
    
    def servResponse(self, command, args):
        if args[0] not in self.ircd.userid:
            return
        udata = self.ircd.userid[args[0]]
        udata.handleCommand("STATS", None, [args[1]])

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
        self.statsCmd = None
    
    def spawn(self):
        self.statsCmd = StatsCommand()
        return {
            "commands": {
                "STATS": self.statsCmd
            },
            "actions": {
                "statsoutput": self.statsCmd.statsChars
            },
            "server": {
                "StatsRequest": self.statsCmd.servResponse
            }
        }
    
    def cleanup(self):
        del self.ircd.commands["STATS"]
        self.ircd.actions["statsoutput"].remove(self.statsCmd.statsChars)
        self.ircd.server_commands["StatsRequest"].remove(self.statsCmd.servResponse)