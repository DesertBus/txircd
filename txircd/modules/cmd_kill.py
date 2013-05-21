from twisted.words.protocols import irc
from txircd.modbase import Command

class KillCommand(Command):
	def onUse(self, user, data):
		target = data["targetuser"]
		reason = "Killed by {}: {}".format(user.nickname, data["reason"])
		target.sendMessage("KILL", ":{} {}".format(user.nickname, data["reason"]), prefix=user.prefix())
		target.disconnect(reason)
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "KILL", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params or len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "KILL", ":Not enough parameters")
			return {}
		if params[0] not in self.ircd.users:
			user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
			return {}
		target = self.ircd.users[params[0]]
		if "o" in target.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You cannot KILL another oper")
			return {}
		return {
			"user": user,
			"targetuser": target,
			"reason": " ".join(params[1:])
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"KILL": KillCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["KILL"]