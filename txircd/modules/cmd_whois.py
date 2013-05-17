from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import epoch, now

irc.RPL_WHOISACCOUNT = "330"
irc.RPL_WHOISSECURE  = "671"

class WhoisCommand(Command):
	def onUse(self, user, data):
		if "targetuser" not in data:
			return
		targets = data["targetuser"]
		for u in targets:
			user.sendMessage(irc.RPL_WHOISUSER, u.nickname, u.username, u.hostname, "*", ":{}".format(u.realname))
			chanlist = u.channels
			chandisplay = []
			for chan in chanlist.iterkeys():
				cdata = self.ircd.channels[chan]
				if chan in user.channels or ("s" not in cdata.mode and "p" not in cdata.mode):
					statuses = u.status(cdata.name)
					status = self.ircd.prefixes[statuses[0]][0] if statuses else ""
					chandisplay.append("{}{}".format(status, cdata.name))
			if chandisplay:
				user.sendMessage(irc.RPL_WHOISCHANNELS, u.nickname, ":{}".format(" ".join(chandisplay)))
			user.sendMessage(irc.RPL_WHOISSERVER, u.nickname, u.server)
			if "accountname" in u.metadata["ext"]:
				user.sendMessage(irc.RPL_WHOISACCOUNT, u.nickname, u.metadata["ext"]["accountname"], ":is logged in as")
			if u.socket.secure:
				user.sendMessage(irc.RPL_WHOISSECURE, u.nickname, ":is using a secure connection")
			if "o" in u.mode:
				user.sendMessage(irc.RPL_WHOISOPERATOR, u.nickname, ":is an IRC operator")
			user.commandExtraHook("WHOIS", { "user": user, "targetuser": u })
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