from twisted.words.protocols import irc
from txircd.modbase import Command

class MessageCommand(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def onUse(self, cmd, user, data):
		if ("targetchan" not in data or not data["targetchan"]) and ("targetuser" not in data or not data["targetuser"]):
			return
		if "message" not in data or not data["message"]:
			user.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
			return
		targetChans = data["targetchan"]
		targetUsers = data["targetuser"]
		channelModifiers = data["chanmod"]
		message = data["message"]
		for index, channel in data["targetchan"].enumerate():
			if channelModifiers[index]:
				prefixLevel = self.prefixes[self.prefix_symbols[channelModifiers[index]]][0]
				for u in channels.users:
					if u.channels[channel.name]["status"] and self.prefixes[u.channels[channel.name]["status"][0]][0] >= prefixLevel:
						u.sendMessage(cmd, message, to="{}{}".format(channelModifiers[index], channel.name), prefix=user.prefix())
			else:
				for u in channel.users:
					u.sendMessage(cmd, message, to=channel.name, prefix=user.prefix())
	
	def processParams(self, cmd, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, cmd, ":Not enough parameters")
			return {}
		if len(params) < 2:
			user.sendMessage(irc.ERR_NOTEXTTOSEND, ":No text to send")
			return {}
		targetChans = []
		targetUsers = []
		targetChanModifiers = []
		for target in params[0].split(","):
			if target in self.ircd.users:
				targetUsers.append(self.ircd.users[target])
			elif target in self.ircd.channels:
				targetChans.append(self.ircd.channels[target])
				targetChanModifiers.append("")
			elif target[0] in self.ircd.prefix_symbols and target[1:] in self.ircd.channels:
				targetChans.append(self.ircd.channels[target[1:]])
				targetChanModifiers.append(target[0])
			else:
				user.sendMessage(irc.ERR_NOSUCHNICK, target, ":No such nick/channel")
		return {
			"user": user,
			"targetchan": targetChans,
			"chanmod": targetChanModifiers,
			"targetuser": targetUsers,
			"message": params[1]
		}

class PrivMsgCommand(Command):
	def __init__(self, msgHandler):
		self.msg_handler = msgHandler
	
	def onUse(self, user, data):
		self.msg_handler.onUse("PRIVMSG", user, data)
	
	def processParams(self, user, params):
		return self.msg_handler.processParams("PRIVMSG", user, params)

class NoticeCommand(Command):
	def __init__(self, msgHandler):
		self.msg_handler = msgHandler
	
	def onUse(self, user, data):
		self.msg_handler.onUse("NOTICE", user, data)
	
	def processParams(self, user, params):
		return self.msg_handler.processParams("NOTICE", user, params)

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		messageHandler = MessageCommand(self.ircd)
		return {
			"commands": {
				"PRIVMSG": PrivMsgCommand(messageHandler),
				"NOTICE": NoticeCommand(messageHandler)
			}
		}
	
	def cleanup():
		del self.ircd.commands["PRIVMSG"]
		del self.ircd.commands["NOTICE"]