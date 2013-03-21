from twisted.words.protocols import irc
from txircd.modbase import Command

class KickCommand(Command):
	def onUse(self, user, data):
		if "targetchan" not in data or "targetuser" not in data:
			return
		cdata = data["targetchan"]
		udata = data["targetuser"]
		reason = data["reason"]
		for u in data["targetchan"].users:
			u.sendMessage("KICK", udata.nickname, ":{}".format(reason), to=cdata.name, prefix=user.prefix())
		udata.leave(cdata)
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "KICK", ":You have not registered")
			return {}
		if not params or len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "KICK", ":Not enough parameters")
			return {}
		if params[0] not in self.ircd.channels:
			user.sendMessage(irc.ERR_NOSUCHCHANNEL, params[0], ":No such channel")
			return {}
		if params[1] not in self.ircd.users:
			user.sendMessage(irc.ERR_NOSUCHNICK, params[1], ":No such nick")
			return {}
		if len(params) < 2 or not params[2]:
			reason = user.nickname
		else:
			reason = params[2]
		return {
			"user": user,
			"targetchan": self.ircd.channels[params[0]],
			"targetuser": self.ircd.users[params[1]],
			"reason": reason
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"KICK": KickCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["KICK"]