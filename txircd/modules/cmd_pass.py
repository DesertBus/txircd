from twisted.words.protocols import irc
from txircd.modbase import Command, Module

class PassCommand(Command, Module):
	def onUse(self, user, data):
		if self.ircd.server_password and not user.password:
			user.registered -= 1
		user.password = data["password"]
		if user.registered == 0:
			user.register()
	
	def processParams(self, user, params):
		if user.registered == 0:
			user.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "PASS", ":Not enough parameters")
			return {}
		return {
			"user": user,
			"password": params[0]
		}
	
	def onConnect(self, user):
		if self.ircd.server_password:
			user.registered += 1 # Make password a required step in registration
	
	def onRegister(self, user):
		if self.ircd.server_password and self.ircd.server_password != user.password:
			user.sendMessage("ERROR", ":Closing link: ({}@{}) [Access denied]".format(user.username, user.hostname), to=None, prefix=None)
			return False

def Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.passcmd = PassCommand()
	
	def spawn(self):
		return {
			"actions": {
				"connect": [self.passcmd.onConnect],
				"register": [self.passcmd.onRegister]
			},
			"commands": {
				"PASS": self.passcmd
			}
		}
	
	def cleanup(self):
		self.ircd.actions["connect"].remove(self.passcmd.onConnect)
		self.ircd.actions["register"].remove(self.passcmd.onRegister)
		del self.ircd.commands["PASS"]
		del self.passcmd