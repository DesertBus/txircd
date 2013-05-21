from twisted.words.protocols import irc
from txircd.modbase import Mode

class TopiclockMode(Mode):
	def checkPermission(self, user, cmd, data):
		if cmd != "TOPIC":
			return data
		if "topic" not in data:
			return data
		targetChannel = data["targetchan"]
		if "t" in targetChannel.mode and not user.hasAccess(self.ircd.channel_minimum_level["TOPIC"], targetChannel.name):
			user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, targetChannel.name, ":You do not have access to change the topic on this channel")
			return {}
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"cnt": TopiclockMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cnt")