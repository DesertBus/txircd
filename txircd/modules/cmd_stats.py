from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now
import collections

class StatsCommand(Command):
	def onUse(self, user, data):
		user.commandExtraHook("STATS", data)
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
		return {
			"user": user,
			"statstype": statschar
		}
	
	def statsChars(self, cmd, data):
		if cmd != "STATS":
			return
		caller = data["user"]
		statschar = data["statstype"]
		if statschar == "o":
			for user in self.ircd.users.itervalues():
				if "o" in user.mode:
					caller.sendMessage(irc.RPL_STATSOPERS, ":{} ({}@{}) Idle: {} secs".format(user.nickname, user.username, user.hostname, epoch(now()) - epoch(user.lastactivity)))
		elif statschar == "p":
			if isinstance(self.ircd.servconfig["server_port_tcp"], collections.Sequence):
				for port in self.ircd.servconfig["server_port_tcp"]:
					caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(port))
			else:
				caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, plaintext)".format(self.ircd.servconfig["server_port_tcp"]))
			if isinstance(self.ircd.servconfig["server_port_ssl"], collections.Sequence):
				for port in self.ircd.servconfig["server_port_ssl"]:
					caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(port))
			else:
				caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, ssl)".format(self.ircd.servconfig["server_port_ssl"]))
			if isinstance(self.ircd.servconfig["server_port_web"], collections.Sequence):
				for port in self.ircd.servconfig["server_port_web"]:
					caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(port))
			else:
				caller.sendMessage(irc.RPL_STATSPORTS, ":{} (clients, web)".format(self.ircd.servconfig["server_port_web"]))
			# Add server ports here when we get s2s
		elif statschar == "u":
			uptime = now() - self.ircd.created
			caller.sendMessage(irc.RPL_STATSUPTIME, ":Server up {}".format(uptime if uptime.days > 0 else "0 days, {}".format(uptime)))

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
				"commandextra": [self.statsCmd.statsChars]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["STATS"]