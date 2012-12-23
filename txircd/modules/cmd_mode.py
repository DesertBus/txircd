from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower

class ModeCommand(Command):
	def onUse(self, user, data):
		if "targetchan" in data:
			cdata = self.ircd.channels[data["targetchan"]]
			self.chanUse(user, cdata, data["modes"])
		elif "targetuser" in data:
			if irc_lower(user) == irc_lower(data["targetuser"]):
				self.userUse(user, data["modes"])
			else:
				self.sendMessage(irc.ERR_NEEDMOREPARAMS, ":Can't operate on modes for other users")
	
	def chanUse(self, user, channel, modes):
		if not modes:
			self.sendMessage(irc.RPL_CHANNELMODEIS, channel.name, channel.modeString())
			self.sendMessage(irc.RPL_CREATIONTIME, channel.name, str(epoch(channel.created)))
			return
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if modetype == -1:
				if param not in self.ircd.users:
					continue
				udata = self.ircd.users[param]
				if channel.name not in udata.channels:
					continue
				if adding:
					status = udata.channels[channel.name]["status"]
					statusList = list(status)
					for index, statusLevel in enumerate(status):
						if self.ircd.prefixes[statusLevel][1] < self.ircd.prefixes[mode][1]:
							statusList.insert(index, mode)
							break
					udata.channels[channel.name]["status"] = "".join(statusList)
					modeDisplay.append(modedata)
				else:
					if mode in udata.channels[channel.name]["status"]:
						udata.channels[channel.name]["status"].remove(mode)
						modeDisplay.append(modedata)
			elif modetype == 0:
				if not param:
					if mode in channels.mode:
						self.ircd.channel_modes[modetype][mode].showParam(user, channels.mode[mode])
					else:
						self.ircd.channel_modes[modetype][mode].showParam(user, [])
				elif adding:
					if mode not in channel.mode:
						channel.mode[mode] = []
					if param not in channel.mode[mode]:
						channel.mode[mode].append(param)
						modeDisplay.append(modeData)
				else:
					if mode not in channel.mode:
						continue
					if param in channel.mode[mode]:
						channel.mode[mode].remove(param)
						modeDisplay.append(modeData)
						if not channel.mode[mode]:
							del channel.mode[mode]
			else:
				if adding:
					if mode in channel.mode and param == channel.mode[mode]:
						continue
					channel.mode[mode] = param
					modeDisplay.append(modeData)
				else:
					if mode not in channel.mode:
						continue
					if modetype == 1 and param != channel.mode[mode]:
						continue
					del channel.mode[mode]
					modeDisplay.append(modeData)
		if modeDisplay:
			adding = None
			modestring = [] # use an array of characters since we're repeatedly adding to this; join at the end
			params = []
			for mode in modeDisplay:
				if mode[1] and adding != "+":
					adding = "+"
					modestring.append("+")
				elif not mode[1] and adding != "-":
					adding = "-"
					modestring.append("-")
				modestring.append(mode[2])
				if mode[3]:
					params.append(mode[3])
			modeLine = "{} {}".format("".join(modestring), " ".join(params)) if params else "".join(modestring)
			for udata in channel.users:
				udata.sendMessage("MODE", modeLine, to=channel.name, prefix=user.prefix())
	
	def userUse(self, user, modes):
		if not modes:
			self.sendMessage(irc.RPL_CHANNELMODEIS, user.modeString())
			return
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if modetype == 0:
				if not param:
					if mode in channels.mode:
						self.ircd.channel_modes[modetype][mode].showParam(user, channels.mode[mode])
					else:
						self.ircd.channel_modes[modetype][mode].showParam(user, [])
				elif adding:
					if mode not in user.mode:
						user.mode[mode] = []
					if param not in user.mode[mode]:
						user.mode[mode].append(param)
						modeDisplay.append(modeData)
				else:
					if mode not in user.mode:
						continue
					if param in user.mode[mode]:
						user.mode[mode].remove(param)
						modeDisplay.append(modeData)
						if not user.mode[mode]:
							del user.mode[mode]
			else:
				if adding:
					if mode in user.mode and param == user.mode[mode]:
						continue
					user.mode[mode] = param
					modeDisplay.append(modeData)
				else:
					if mode not in user.mode:
						continue
					if modetype == 1 and param != user.mode[mode]:
						continue
					del user.mode[mode]
					modeDisplay.append(modeData)
		if modeDisplay:
			adding = None
			modestring = [] # use an array of characters since we're repeatedly adding to this; join at the end
			params = []
			for mode in modeDisplay:
				if mode[1] and adding != "+":
					adding = "+"
					modestring.append("+")
				elif not mode[1] and adding != "-":
					adding = "-"
					modestring.append("-")
				modestring.append(mode[2])
				if mode[3]:
					params.append(mode[3])
			modeLine = "{} {}".format("".join(modestring), " ".join(params)) if params else "".join(modestring)
			user.sendMessage("MODE", modeLine, prefix=user.prefix())
	
	def processParams(self, user, params):
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters")
			return {}
		if params[0] in self.ircd.users:
			if len(params) > 1 and params[1]:
				modeChanges = []
				adding = True
				current_param = 2
				for mode in params[1]:
					if mode == "+":
						adding = True
					elif mode == "-":
						adding = False
					else:
						if mode not in self.ircd.user_mode_type:
							user.sendMessage(irc.ERR_UMODEUNKNOWNFLAG, mode, ":is unknown mode char to me")
							continue
						mode_type = self.ircd.user_mode_type[mode]
						if mode_type == 1 or (adding and mode_type == 2):
							if len(params) <= current_param:
								continue # Mode must have param that wasn't provided
							modeChanges.append([mode_type, adding, mode, params[current_param]])
							current_param += 1
						else:
							modeChanges.append([mode_type, adding, mode, None])
			return {
				"user": user,
				"targetuser": self.ircd.users[params[0]],
				"modes": []
			}
		if params[0] in self.ircd.channels:
			if len(params) > 1 and params[1]:
				if params[0] not in user.channels:
					user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, params[0], ":You must have channel halfop access or above to set channel modes")
					return {}
				modeChanges = []
				adding = True
				current_param = 2
				for mode in params[1]:
					if mode == "+":
						adding = True
					elif mode == "-":
						adding = False
					else:
						if mode not in self.ircd.channel_mode_type:
							user.sendMessage(irc.ERR_UNKNOWNMODE, mode, ":is unknown mode char to me")
							continue
						mode_type = self.ircd.channel_mode_type[mode]
						if mode_type == 1 or (adding and mode_type == 2):
							if len(params) <= current_param:
								continue # Mode must have param that wasn't provided
							modeChanges.append([mode_type, adding, mode, params[current_param]])
							current_param += 1
						else:
							modeChanges.append([mode_type, adding, mode, None])
			return {
				"user": user,
				"targetchan": self.ircd.channels[params[0]],
				"modes": []
			}
		user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
		return {}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"MODE": ModeCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["MODE"]