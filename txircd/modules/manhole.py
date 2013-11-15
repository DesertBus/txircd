from twisted.conch.manhole_tap import makeService

class Spawner(object):
    def __init__(self, ircd):
        self.manhole = makeService({
            'namespace': {'ircd': ircd},
            'passwd': 'manhole.passwd',
            'telnetPort': None,
            'sshPort': '65432'
        })
    
    def spawn(self):
        self.manhole.startService()
        return {}

    def cleanup(self):
        self.manhole.stopService()
