from txircd.modbase import Command

class PingCommand(Command):
	def onUse(self, user, data):
		if params:
			self.sendMessage("PONG", ":{}".format(data["params"][0]), to=self.ircd.server_name)
		else:
			self.sendMessage(irc.ERR_NOORIGIN, ":No origin specified")
	
	def updateActivity(self, user):
		pass

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"PING": PingCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["PING"]