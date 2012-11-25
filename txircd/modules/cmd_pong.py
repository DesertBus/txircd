from txircd.modbase import Command

class PongCommand(Command):
	def onUse(self, user, params):
		user.lastpong = now()

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"PONG": PongCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["PONG"]