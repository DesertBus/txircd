from twisted.words.protocols import irc
from txircd.modbase import Command

class SamodeCommand(Command):
	def onUse(self, user, data):
		if "targetchan" in data:
			self.chanUse(user, data["targetchan"], data["modes"])
		elif "targetuser" in data:
			self.userUse(user, data["targetuser"], data["modes"])
	
	def chanUse(self, user, channel, modes):
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if not adding and modetype >= 0 and mode not in channel.mode:
				continue # mode is not set on channel; cannot remove
			if adding: # check parameter sanity
				if modetype >= 0:
					allowed, param = self.ircd.channel_modes[modetype][mode].checkSet(user, channel, param)
					if not allowed:
						continue
				else:
					if param not in self.ircd.users:
						continue
					uparam = self.ircd.users[param]
					if uparam not in channel.users:
						continue
					if mode in uparam.status(channel.name):
						continue
					param = uparam.nickname
			else:
				if modetype >= 0:
					allowed, param = self.ircd.channel_modes[modetype][mode].checkUnset(user, channel, param)
					if not allowed:
						continue
				else:
					if param not in self.ircd.users:
						continue
					uparam = self.ircd.users[param]
					if uparam not in channel.users:
						continue
					if mode not in uparam.status(channel.name):
						continue
					param = uparam.nickname
			modedata[3] = param
			if modetype == -1:
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
				if adding:
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
					if mode in channel.mode and param == channelmode[mode]:
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
			modestring = []
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
	
	def userUse(self, user, target, modes):
		modeDisplay = []
		for modedata in modes:
			modetype, adding, mode, param = modedata
			if not adding and mode not in user.mode:
				continue # cannot unset mode that's not set
			if adding:
				allowed, param = self.ircd.user_modes[modetype][mode].checkSet(user, target, param)
				if not allowed:
					continue
			else:
				allowed, param = self.ircd.user_modes[modetype][mode].checkUnset(user, target, param)
				if not allowed:
					continue
			modedata[3] = param
			if modetype == 0:
				if adding:
					if mode not in target.mode:
						target.mode[mode] = []
					if param not in target.mode[mode]:
						target.mode[mode].append(param)
						modeDisplay.append(modedata)
				else:
					if mode not in target.mode:
						continue
					if param in target.mode[mode]:
						taret.mode[mode].remove(param)
						modeDisplay.append(modedata)
						if not target.mode[mode]:
							del target.mode[mode]
			else:
				if adding:
					if mode in target.mode and param == target.mode[mode]:
						continue
					target.mode[mode] = param
					modeDisplay.append(modedata)
				else:
					if mode not in target.mode:
						continue
					if modetype == 1 and param != target.mode[mode]:
						continue
					del target.mode[mode]
					modeDisplay.append(modedata)
		if modeDisplay:
			adding = None
			modestring = []
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
			target.sendMessage("MODE", modeLine, prefix=user.prefix())
			user.sendMessage("NOTICE", ":*** SAMODE used on {}; changed modes {}".format(target.nickname, modeLine))
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "SAMODE", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		if not params or len(params) < 2:
			user.sendMessage(irc.ERR_NEEDMOREPARAMS, "SAMODE", ":Not enough parameters")
			return {}
		
		if params[0] in self.ircd.users:
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
					if mode_type == 1 or (adding and mode_type == 2) or mode_type == 0:
						if len(params) <= current_param:
							continue
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
					if mode_type == -1 or mode_type == 0 or mode_type == 1 or (adding and mode_type == 2):
						if len(params) <= current_param:
							continue
						modeChanges.append([mode_type, adding, mode, params[current_param]])
						current_param += 1
					else:
						modeChanges.append([mode_type, adding, mode, None])
			return {
				"user": user,
				"targetchan": self.ircd.channels[params[0]],
				"modes": modeChanges
			}
		user.sendMessage(irc.ERR_NOSUCHNICK, params[0], ":No such nick/channel")
		return {}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"SAMODE": SamodeCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["SAMODE"]