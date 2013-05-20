from twisted.words.protocols import irc
from txircd.modbase import Module
from txircd.utils import irc_lower
from fnmatch import fnmatch

irc.ERR_CHANNOTALLOWED = "926" # I fully admit that this is an entirely made-up numeric name.

class DenychansModule(Module):
	def denyChannels(self, user, cmd, data):
		if "o" in user.mode:
			return data
		if cmd != "JOIN":
			return data
		channels = data["targetchan"]
		keys = data["keys"]
		remove = []
		for channel in channels:
			lowerName = irc_lower(channel.name)
			safe = False
			if "channel_allowchans" in self.ircd.servconfig:
				for chanmask in self.ircd.servconfig["channel_allowchans"]:
					if fnmatch(lowerName, irc_lower(chanmask)):
						safe = True
			if not safe:
				for chanmask in self.ircd.servconfig["channel_denychans"]:
					if fnmatch(lowerName, irc_lower(chanmask)):
						remove.append(channel)
						user.sendMessage(irc.ERR_CHANNOTALLOWED, channel.name, ":Channel {} is forbidden".format(channel.name))
						break
		for chan in remove:
			index = channels.index(chan)
			channels.pop(index)
			keys.pop(index)
		data["targetchan"] = channels
		data["keys"] = keys
		return data

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
		self.denychans = None
	
	def spawn(self):
		if "channel_denychans" not in self.ircd.servconfig:
			self.ircd.servconfig["channel_denychans"] = []
		self.denychans = DenychansModule().hook(self.ircd)
		return {
			"actions": {
				"commandpermission": [self.denychans.denyChannels]
			}
		}
	
	def cleanup(self):
		self.ircd.actions["commandpermission"].remove(self.denychans.denyChannels)