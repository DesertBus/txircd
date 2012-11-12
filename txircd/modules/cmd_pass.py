from twisted.words.protocols import irc
from txircd.modbase import Command, Module

class PassCommand(Command, Module):
	def onUse(self, user, params):
		if user.registered == 0:
			user.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
			return
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "PASS", ":Not enough parameters")
			return
		user.password = params[0]
	
	def onRegister(self, user):
		if self.ircd.server_password and self.ircd.server_password != user.password:
			user.sendMessage("ERROR", ":Closing link: ({}@{}) [Access denied]".format(user.username, user.hostname), to=None, prefix=None)
			return False

def spawn():
	passcmd = PassCommand()
	return {
		"actions": [passcmd],
		"commands": {
			"PASS": passcmd
		}
	}