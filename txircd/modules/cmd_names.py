from twisted.words.protocols import irc
from txircd.modbase import Command

class NamesCommand(Command):
	def onUse(self, user, data):
		for chan in data["targetchan"]:
			user.report_names(chan)
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "NAMES", ":You have not registered")
			return {}
		if params:
			channels = params[0].split(",")
		else:
			channels = user.channels.keys()
		chan_param = []
		for chan in channels:
			if chan in self.ircd.channels:
				chan_param.append(self.ircd.channels[chan])
			else:
				user.sendMessage(irc.ERR_NOSUCHNICK, chan, ":No such nick/channel")
		return {
			"user": user,
			"targetchan": chan_param
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"NAMES": NamesCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["NAMES"]