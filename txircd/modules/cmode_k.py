from twisted.words.protocols import irc
from txircd.modbase import Mode

class PasswordMode(Mode):
	def checkUnset(self, user, target, param):
		if param == target.mode["k"]:
			return True
		return False
	
	def commandPermission(self, user, cmd, data):
		if cmd != "JOIN":
			return data
		channels = data["targetchan"]
		keys = data["keys"]
		removeChannels = []
		for index, chan in channels.enumerate():
			if "k" in chan.mode and chan.mode["k"] != keys[index]:
				removeChannels.append(chan)
				user.sendMessage(irc.ERR_BADCHANNELKEY, chan.name, ":Cannot join channel (Incorrect channel key)")
		for chan in removeChannels:
			index = channels.index(chan) # We need to do this anyway to eliminate the effects of shifting when removing earlier elements
			channels.pop(index)
			keys.pop(index)
		data["targetchan"] = channels
		data["keys"] = keys
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"cuk": PasswordMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cuk")