from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import crypt

class OperCommand(Command):
	def onUse(self, user, data):
		if data["username"] not in self.ircd.servconfig["oper_logins"] or self.ircd.servconfig["oper_logins"][data["username"]] != crypt(data["password"], self.ircd.servconfig["oper_logins"][data["username"]]):
			user.sendMessage(irc.ERR_PASSWDMISMATCH, ":Password incorrect")
		else:
			if "o" not in user.mode:
				user.mode["o"] = None
				user.sendMessage("MODE", "+o")
			user.sendMessage(irc.RPL_YOUREOPER, ":You are now an IRC operator")
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "OPER", ":You have not registered")
			return {}
		if len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "OPER", ":Not enough parameters")
			return {}
		if self.ircd.servconfig["oper_ips"] and user.ip not in self.ircd.servconfig["oper_ips"]:
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
	
	def spawn(self):
		return {
			"commands": {
				"OPER": OperCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["OPER"]