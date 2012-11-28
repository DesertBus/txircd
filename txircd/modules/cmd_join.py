from twisted.words.protocols import irc
from txircd.modbase import Command

class JoinCommand(Command):
	def onUse(self, user, data):
		if "targetchan" not in data or not data["targetchan"]:
			return
		for chan in data["targetchan"]:
			user.join(chan)
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "JOIN", ":Not enough parameters")
			return {}
		channels = params[0].split(",")
		keys = params[1].split(",") if len(params) > 1 else []
		while len(keys) < len(channels):
			keys.append(None)
		joining = []
		for i in range(0, len(channels)):
			joining.append({"channel": channels[i][:64], "key": keys[i]})
		remove = []
		for chan in joining:
			if chan["channel"] in user.channels:
				remove.add(chan)
		for chan in remove:
			joining.remove(chan)
		channels = keys = []
		for chan in joining:
			channels.append(chan["channel"])
			keys.append(chan["key"])
		return {
			"user": user,
			"targetchan": params[0].split(","),
			"keys": params[1].split(",") if len(params) > 1 else [],
			"moreparams": params[2:]
		}

def Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"JOIN": JoinCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["JOIN"]