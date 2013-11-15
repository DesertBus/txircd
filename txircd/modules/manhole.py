from twisted.conch.manhole_tap import makeService
from twisted.internet import reactor

class Spawner(object):
    def __init__(self, ircd):
        self.manhole = makeService({
            'namespace': {'ircd': ircd},
            'passwd': 'manhole.passwd',
            'telnetPort': None,
            'sshPort': 'tcp:65432:interface=127.0.0.1'
        })
    
    def spawn(self):
        # Wait 100ms in event of a rehash so that the old module
        # has time to shut down. Could cause race conditions!
        reactor.callLater(0.1, self.manhole.startService)
        return {}

    def cleanup(self):
        self.manhole.stopService()
