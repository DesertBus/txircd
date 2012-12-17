from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.channel import IRCChannel

class JoinCommand(Command):
	def onUse(self, user, data):
		if "targetchan" not in data or not data["targetchan"]:
			return
		for chan in data["targetchan"]:
			if chan.name not in self.ircd.channels: # creating a channel
				self.ircd.channels[chan.name] = chan
			user.join(chan.name)
	
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
			joining.append({"channel": channels[i][:64], "key": keys[i] if len(keys) >= i else ""})
		remove = []
		for chan in joining:
			if chan["channel"] in user.channels:
				remove.append(chan)
			if chan["channel"][0] not in self.ircd.channel_prefixes:
				user.sendMessage(irc.ERR_BADCHANMASK, chan["channel"], ":Bad Channel Mask")
				remove.append(chan)
		for chan in remove:
			joining.remove(chan)
		channels = keys = []
		for chan in joining:
			channels.append(self.ircd.channels[chan["channel"]] if chan["channel"] in self.ircd.channels else IRCChannel(chan["channel"]))
			keys.append(chan["key"])
		return {
			"user": user,
			"targetchan": channels,
			"keys": keys,
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