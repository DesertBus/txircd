from txircd.modbase import Command
from txircd.utils import now

class PongCommand(Command):
	def onUse(self, user, data):
		user.lastpong = now()
	
	def updateActivity(self, user):
		pass

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"PONG": PongCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["PONG"]