from txircd.utils import CaseInsensitiveDictionary, now

class IRCChannel(object):
	def __init__(self, ircd, name):
		self.ircd = ircd
		self.name = name
		self.created = now()
		self.topic = ""
		self.topicSetter = ""
		self.topicTime = now()
		self.mode = {}
		self.users = set()
		self.metadata = {}
		self.cache = {}
	
	def modeString(self, user):
		modes = [] # Since we're appending characters to this string, it's more efficient to store the array of characters and join it rather than keep making new strings
		params = []
		for mode, param in self.mode.iteritems():
			modetype = self.ircd.channel_mode_type[mode]
			if modetype > 0:
				modes.append(mode)
				if param:
					params.append(self.ircd.channel_modes[modetype][mode].showParam(user, param))
		return ("+{} {}".format("".join(modes), " ".join(params)) if params else "".join(modes))
	
	def setTopic(self, topic, setter):
		self.topic = topic
		self.topicSetter = setter
		self.topicTime = now()
	
	def getMetadata(self, key):
		if key in self.metadata:
			return self.metadata[key]
		return ""