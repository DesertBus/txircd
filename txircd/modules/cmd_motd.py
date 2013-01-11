from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import chunk_message

class MOTDCommand(Command):
	def onUse(self, user, data):
		user.send_motd()
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "MOTD", ":You have not registered")
			return {}
		return {
			"user": user
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"MOTD": MOTDCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["MOTD"]