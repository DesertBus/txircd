from twisted.words.protocols import irc
from txircd.modbase import Command
from txircd.utils import irc_lower, epoch

class ModeCommand(Command):
	def onUse(self, user, data):
		if "targetchan" in data:
			self.chanUse(user, data["targetchan"], data["modes"])
		elif "targetuser" in data:
			if user == data["targetuser"]:
				self.userUse(user, data["modes"])
			else:
				user.sendMessage(irc.ERR_USERSDONTMATCH, ":Can't operate on modes for other users")
	
	def chanUse(self, user, channel, modes):
		if not modes:
			user.sendMessage(irc.RPL_CHANNELMODEIS, channel.name, channel.modeString(user))
			user.sendMessage(irc.RPL_CREATIONTIME, channel.name, str(epoch(channel.created)))
			return
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if not (modetype == 0 and param is None): # ignore these checks for listing list modes
				if not adding and modetype >= 0 and mode not in channel.mode:
					continue # channel does not have mode set; cannot remove
				if adding:
					allowed, param = self.ircd.channel_modes[modetype][mode].checkSet(user, channel, param) if modetype >= 0 else self.ircd.prefixes[mode][2].checkSet(user, channel, param)
					if not allowed:
						continue
				else:
					allowed, param = self.ircd.channel_modes[modetype][mode].checkUnset(user, channel, param) if modetype >= 0 else self.ircd.prefixes[mode][2].checkUnset(user, channel, param)
					if not allowed:
						continue
			modedata[3] = param # update the param in modedata so that the displayed mode change is shown correctly
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
					if mode not in statusList: # no status to put this one before was found, so this goes at the end
						statusList.append(mode)
					udata.channels[channel.name]["status"] = "".join(statusList)
					modeDisplay.append(modedata)
				else:
					if mode in udata.channels[channel.name]["status"]:
						udata.channels[channel.name]["status"] = udata.channels[channel.name]["status"].replace(mode, "")
						modeDisplay.append(modedata)
			elif modetype == 0:
				if not param:
					self.ircd.channel_modes[modetype][mode].showParam(user, channel)
				elif adding:
					if mode not in channel.mode:
						channel.mode[mode] = []
					if param not in channel.mode[mode]:
						channel.mode[mode].append(param)
						modeDisplay.append(modedata)
				else:
					if mode not in channel.mode:
						continue
					if param in channel.mode[mode]:
						channel.mode[mode].remove(param)
						modeDisplay.append(modedata)
						if not channel.mode[mode]:
							del channel.mode[mode]
			else:
				if adding:
					if mode in channel.mode and param == channel.mode[mode]:
						continue
					channel.mode[mode] = param
					modeDisplay.append(modedata)
				else:
					if mode not in channel.mode:
						continue
					if modetype == 1 and param != channel.mode[mode]:
						continue
					del channel.mode[mode]
					modeDisplay.append(modedata)
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
			user.sendMessage(irc.RPL_UMODEIS, user.modeString(user))
			return
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if not (modetype == 0 and param is None): # ignore these checks for listing list modes
				if not adding and mode not in user.mode:
					continue # Cannot unset mode that's not set
				if adding:
					allowed, param = self.ircd.user_modes[modetype][mode].checkSet(user, user, param)
					if not allowed:
						continue
				else:
					allowed, param = self.ircd.user_modes[modetype][mode].checkUnset(user, user, param)
					if not allowed:
						continue
			modedata[3] = param # update the param in modedata so that the displayed mode change is shown correctly
			if modetype == 0:
				if not param:
					self.ircd.user_modes[modetype][mode].showParam(user, user)
				elif adding:
					if mode not in user.mode:
						user.mode[mode] = []
					if param not in user.mode[mode]:
						user.mode[mode].append(param)
						modeDisplay.append(modedata)
				else:
					if mode not in user.mode:
						continue
					if param in user.mode[mode]:
						user.mode[mode].remove(param)
						modeDisplay.append(modedata)
						if not user.mode[mode]:
							del user.mode[mode]
			else:
				if adding:
					if mode in user.mode and param == user.mode[mode]:
						continue
					user.mode[mode] = param
					modeDisplay.append(modedata)
				else:
					if mode not in user.mode:
						continue
					if modetype == 1 and param != user.mode[mode]:
						continue
					del user.mode[mode]
					modeDisplay.append(modedata)
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
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTREGISTERED, "MODE", ":You have not registered")
			return {}
		if not params:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "MODE", ":Not enough parameters")
			return {}
		if params[0] in self.ircd.users:
			modeChanges = []
			if len(params) > 1 and params[1]:
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
						if mode_type == 1 or (adding and mode_type == 2) or (mode_type == 0 and len(params) > current_param):
							if len(params) <= current_param:
								continue # Mode must have param that wasn't provided
							modeChanges.append([mode_type, adding, mode, params[current_param]])
							current_param += 1
						else:
							modeChanges.append([mode_type, adding, mode, None])
			return {
				"user": user,
				"targetuser": self.ircd.users[params[0]],
				"modes": modeChanges
			}
		if params[0] in self.ircd.channels:
			cdata = self.ircd.channels[params[0]]
			modeChanges = []
			if len(params) > 1 and params[1]:
				if params[0] not in user.channels or not user.hasAccess(cdata.name, self.ircd.servconfig["channel_minimum_level"]["MODE"]):
					if len(params) > 2:
						user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, params[0], ":You must have channel operator access to set channel modes")
						return {}
					for mode in params[1]:
						if mode == "+" or mode == "-":
							continue
						if self.ircd.channel_mode_type[mode] != 0:
							user.sendMessage(irc.ERR_CHANOPRIVSNEEDED, params[0], ":You must have channel operator access to set channel modes")
							return {} # user is trying to change modes; abort
					# User isn't trying to change modes; go ahead and continue
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
						if mode_type == -1 or (mode_type == 0 and len(params) > current_param) or mode_type == 1 or (adding and mode_type == 2):
							if len(params) <= current_param:
								continue # Mode must have param that wasn't provided
							modeChanges.append([mode_type, adding, mode, params[current_param]])
							current_param += 1
						else:
							modeChanges.append([mode_type, adding, mode, None])
			return {
				"user": user,
				"targetchan": cdata,
				"modes": modeChanges
			}
		user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
		return {}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		if "channel_minimum_level" not in self.ircd.servconfig:
			self.ircd.servconfig["channel_minimum_level"] = {}
		if "MODE" not in self.ircd.servconfig["channel_minimum_level"]:
			self.ircd.servconfig["channel_minimum_level"]["MODE"] = "o"
		return {
			"commands": {
				"MODE": ModeCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["MODE"]