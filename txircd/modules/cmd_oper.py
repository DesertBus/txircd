from txircd.modbase import Command
from txircd.utils import crypt

class OperCommand(Command):
	def onUse(self, user, data):
		if data["username"] not in self.ircd.oper_logins or self.ircd.oper_logins[data["username"]] != crypt(data["password"], self.ircd.oper_logins[data["username"]]):
			user.sendMessage(irc.ERR_PASSWDMISMATCH, ":Password incorrect")
		else:
			user.mode["o"] = True
			user.sendMessage(irc.RPL_YOUREOPER, ":You are now an IRC operator")
	
	def processParams(self, user, params):
		if len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters")
			return {}
		if user.ip not in self.ircd.oper_ips:
			user.sendMessage(irc.ERR_NOOPERHOST, ":No O-lines for your host")
			return {}
		return {
			"user": user,
			"username": params[0],
			"password": params[1]
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"OPER": OperCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["OPER"]