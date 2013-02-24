from twisted.words.protocols import irc
from txircd.modbase import Command

class AwayCommand(Command):
	def onUse(self, user, data):
		if "reason" in data:
			user.metadata["away"] = data["reason"]
			user.sendMessage(irc.RPL_NOWAWAY, ":You have been marked as being away")
		else:
			if "away" in user.metadata:
				del user.metadata["away"]
			user.sendMessage(irc.RPL_UNAWAY, ":You are no longer marked as being away")
	
	def processParams(self, user, params):
		if not params:
			return {
				"user": user
			}
		return {
			"user": user,
			"reason": params[0]
		}
	
	def privmsgReply(self, command, data):
		if command != "PRIVMSG":
			return
		if "targetuser" not in data:
			return
		sourceUser = data["user"]
		for user in data["targetuser"]:
			udata = self.ircd.users[user]
			if "away" in udata.metadata:
				sourceUser.sendMessage(irc.RPL_AWAY, udata.nickname, ":{}".format(udata.metadata["away"]))
	
	def whoisLine(self, command, data):
		if command != "WHOIS":
			return
		user = data["user"]
		target = data["targetuser"]
		if "away" in target.metadata:
			user.sendMessage(irc.RPL_AWAY, target.username, ":{}".format(target.metadata["away"]))

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.awayCmd = None
	
	def spawn(self):
		self.awayCmd = AwayCommand()
		return {
			"commands": {
				"AWAY": self.awayCmd
			},
			"actions": {
				"commandextra": [self.awayCmd.privmsgReply, self.awayCmd.whoisLine]
		}
	
	def cleanup(self):
		self.ircd.actions["commandextra"].remove(self.awayCmd.privmsgReply)
		del self.ircd.commands["AWAY"]