from twisted.words.protocols import irc
from txircd.modbase import Command

class PartCommand(Command):
	def onUse(self, user, data):
		if "targetchan" not in data:
			return
		for channel in data["targetchan"]:
			cdata = self.ircd.channels[channel]
			for u in cdata.users.itervalues():
				u.sendMessage("PART", ":{}".format(data["reason"]), to=cdata.name, prefix=user.prefix())
			user.leave(channel)
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "PART", ":Not enough parameters")
			return {}
		channels = params[0].split(",")
		reason = params[1] if len(params) > 1 else user.nickname
		delChan = []
		for chan in channels:
			if chan not in self.ircd.channels:
				user.sendMessage(irc.ERR_NOSUCHCHANNEL, channel, ":No such channel")
				delChan.append(chan)
			elif chan not in user.channels:
				user.sendMessage(irc.ERR_NOTONCHANNEL, channel, ":You're not on that channel")
				delChan.append(chan)
		for chan in delChan:
			channels.remove(chan)
		return {
			"user": user,
			"targetchan": channels,
			"reason": reason
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"PART": PartCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["PART"]