from twisted.words.protocols import irc
from txircd.modbase import Mode

class InviteOnlyMode(Mode):
	def commandPermission(self, user, cmd, data):
		if cmd != "JOIN":
			return data
		targetChannels = data["targetchan"]
		keys = data["keys"]
		removeChannels = []
		for channel in targetChannels:
			if "i" in channel.mode and "invites" in user.cache and channel.name not in user.cache["invites"]:
				if "invite_except" not in user.cache:
					user.cache["invite_except"] = { channel.name: False }
					return "again"
				if channel.name not in user.cache["invite_except"]:
					user.cache["invite_except"][channel.name] = False
					return "again"
				if user.cache["invite_except"][channel.name]:
					del user.cache["invite_except"][channel.name]
				else:
					removeChannels.append(channel)
					user.sendMessage(irc.ERR_INVITEONLYCHAN, channel.name, ":Cannot join channel (Invite only)")
			elif "invites" in user.cache and channel.name in user.cache["invites"]:
				if "invite_except" in user.cache and channel.name in user.cache["invite_except"]:
					del user.cache["invite_except"][channel.name]
				user.cache["invites"].remove(channel.name)
		for channel in removeChannels:
			index = targetChannels.index(channel)
			targetChannels.pop(index)
			keys.pop(index)
		data["targetchan"] = targetChannels
		data["keys"] = keys
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"cni": InviteOnlyMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cni")