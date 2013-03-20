from twisted.words.protocols import irc
from txircd.modbase import Mode

class ModeratedMode(Mode):
	def checkPermission(self, user, cmd, data):
		if cmd not in ["PRIVMSG", "NOTICE"]:
			return data
		targetChannels = data["targetchan"]
		chanModList = data["chanmod"]
		removeChannels = []
		for channel in targetChannels:
			if "m" in channel.mode and not user.hasAccess("v"):
				removeChannels.append(channel)
				user.sendMessage(irc.ERR_CANNOTSENDTOCHAN, channel.name, ":Cannot send to channel (+m)")
		for channel in removeChannels:
			index = targetChannels.index(channel)
			targetChannels.pop(index)
			chanModList.pop(index)
		data["targetchan"] = targetChannels
		data["chanmod"] = chanModList
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"cnm": ModeratedMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cnm")