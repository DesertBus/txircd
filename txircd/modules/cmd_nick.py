from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import VALID_USERNAME, irc_lower

class NickCommand(Command):
	def onUse(self, user, data):
		if user.registered == 0:
			user.nick(data["nick"])
		else:
			if not user.nickname:
				user.registered -= 1
			user.nickname = data["nick"]
			if user.registered == 0:
				user.register()
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NONICKNAMEGIVEN, ":No nickname given")
			return {}
		if not params[0]:
			user.sendMessage(irc.ERR_ERRONEUSNICKNAME, "*", ":Erroneous nickname")
			return {}
		if not VALID_USERNAME.match(params[0]):
			user.sendMessage(irc.ERR_ERRONEUSNICKNAME, params[0], ":Erroneous nickname")
			return {}
		if params[0] == user.nickname:
			return {}
		if params[0] in self.ircd.users and irc_lower(params[0]) != irc_lower(user.nickname):
			user.sendMessage(irc.ERR_NICKNAMEINUSE, self.ircd.users[params[0]].nickname, ":Nickname is already in use")
			return {}
		return {
			"user": user,
			"nick": params[0]
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"NICK": NickCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["NICK"]