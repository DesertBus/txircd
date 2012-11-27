from twisted.words.protocols import irc
from txircd.modbase import Command

class UserCommand(Command):
	def onUse(self, user, data):
		if not user.username:
			user.registered -= 1
		user.username = data["ident"]
		user.realname = data["gecos"]
		if user.registered == 0:
			user.register()
	
	def processParams(self, user, params):
		if user.registered == 0:
			user.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
			return {}
		if params and len(params) < 4:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Not enough parameters")
			return {}
		ident = filter(lambda x: x in string.ascii_letters + string.digits + "-_", params[0])[:12]
		if not ident:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Your username is not valid")
			return {}
		return {
			"user": user,
			"ident": ident,
			"gecos": params[3]
		}

def Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"USER": UserCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["USER"]