from twisted.words.protocols import irc
from txircd.modbase import Command

class UserCommand(Command):
	def onUse(self, user, params):
		if user.registered == 0:
			self.sendMessage(irc.ERR_ALREADYREGISTRED, ":Unauthorized command (already registered)")
			return
		if params and len(params) < 4:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Not enough parameters")
		if not user.username:
			user.registered -= 1
		user.username = filter(lambda x: x in string.ascii_letters + string.digits + "-_", params[0])[:12]
		if not user.username:
			user.registered += 1
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "USER", ":Your username is not valid")
			return
		user.realname = params[3]
		if user.registered == 0:
			user.register()

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