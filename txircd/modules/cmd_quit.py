from twisted.words.protocols import irc
from txircd.modbase import Command

class QuitCommand(Command):
	def onUse(self, user, data):
		reason = "Quit: {}".format(data["reason"]) if "reason" in data and data["reason"] else "Client Quit"
		user.disconnect(reason)
	
	def processParams(self, user, params):
		reason = params[0] if params and params[0] else "Client exited"
		return {
			"user": user,
			"reason": reason
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"QUIT": QuitCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["QUIT"]