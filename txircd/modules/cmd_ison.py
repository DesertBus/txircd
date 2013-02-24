from twisted.words.protocols import irc
from txircd.modbase import Command

class IsonCommand(Command):
	def onUse(self, user, data):
		reply = []
		for nick in data["nicklist"]:
			if nick in self.ircd.users:
				reply.append(self.ircd.users[nick].nickname)
		self.sendMessage(irc.RPL_ISON, ":{}".format(" ".join(reply)))
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "ISON", ":You have not registered")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "ISON", ":Not enough parameters")
			return {}
		extraNicks = params.pop().split(" ")
		return {
			"user": user,
			"nicklist": params + extraNicks
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"ISON": IsonCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["ISON"]