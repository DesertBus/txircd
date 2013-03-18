from twisted.words.protocols import irc
from txircd.modbase import Command

class PingCommand(Command):
	def onUse(self, user, data):
		if data["params"]:
			user.sendMessage("PONG", ":{}".format(data["params"][0]), to=self.ircd.servconfig["server_name"], prefix=None)
		else:
			user.sendMessage(irc.ERR_NOORIGIN, ":No origin specified")
	
	def updateActivity(self, user):
		pass

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"PING": PingCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["PING"]