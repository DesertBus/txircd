from twisted.words.protocols import irc
from txircd.modbase import Command

class GlobopsCommand(Command):
	def onUse(self, user, data):
		if "message" in data:
			message = data["message"]
			for u in self.ircd.users:
				if "o" in u.mode:
					u.sendMessage("NOTICE", ":*** GLOBOPS from {}: {}".format(user.nickname, message))
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "GLOBOPS", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - command GLOBOPS requires oper privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "GLOBOPS", ":Not enough parameters")
			return {}
		return {
			"user": user,
			"message": " ".join(params)
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"GLOBOPS": GlobopsCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["GLOBOPS"]