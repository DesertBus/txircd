from twisted.words.protocols import irc
from txircd.modbase import Command
import re

irc.RPL_BADWORDADDED = "927"
irc.RPL_BADWORDREMOVED = "928"
irc.ERR_NOSUCHBADWORD = "929"

class BadwordCommand(Command):
	def __init__(self):
		self.badwords = {}
	
	def onUse(self, user, data):
		if "replacement" in data:
			badword = data["badword"]
			replacement = data["replacement"]
			self.badwords[badword] = replacement
			user.sendMessage(irc.RPL_BADWORDADDED, badword, ":{}".format(replacement))
		else:
			del self.badwords[badword]
			user.sendMessage(irc.RPL_BADWORDREMOVED, badword, ":Badword removed")
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "BADWORD", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "BADWORD", ":Not enough parameters")
			return {}
		if param[0][0] == "-":
			badword = params[0][1:]
			if badword not in self.badwords:
				user.sendMessage(irc.ERR_NOSUCHBADWORD, badword, ":No such badword")
				return {}
			return {
				"user": user,
				"badword": badword
			}
		return {
			"user": user,
			"badword": params[0],
			"replacement": params[1] if len(params) > 1 else ""
		}
	
	def censor(self, user, command, data):
		if command not in ["PRIVMSG", "NOTICE", "TOPIC"]:
			return data
		if "o" in user.mode: # don't censor opers
			return data
		if command == "PRIVMSG" or command == "NOTICE":
			message = data["message"]
			for mask, replacement in self.badwords.iteritems():
				message = re.sub(mask, replacement, message, flags=re.IGNORECASE)
			data["message"] = message
			return data
		if command == "TOPIC":
			topic = data["topic"]
			for mask, replacement in self.badwords.iteritems():
				topic = re.sub(mask, replacement, topic, flags=re.IGNORECASE)
			data["topic"] = topic
			return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.badwordCmd = None
	
	def spawn(self):
		self.badwordCmd = BadwordCommand()
		return {
			"commands": {
				"BADWORD": self.badwordCmd,
			},
			"actions": {
				"commandpermission": [self.badwordCmd.censor]
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["BADWORD"]
		self.ircd.actions["commandpermission"].remove(self.badwordCmd.censor)
	
	def data_serialize(self):
		return [True, self.badwordCmd.badwords]
	
	def data_unserialize(self, data):
		self.badwordCmd.badwords = data