#!/usr/bin/python
"""This is a udp / binary version of PixelFlut

Inspired by the PixelFlut projector on eth0:winter 2016 and
code from https://github.com/defnull/pixelflut/
"""

__version__ = 0.3
__author__ = "Jan Klopper <jan@underdark.nl>"

if __name__ == '__main__':
  # avoid nasty exception on python closing time
  from gevent import spawn, monkey
  monkey.patch_all()

import struct
import time
import socket

UDP_IP = "127.0.0.1"
UDP_PORT = 5005
DISCOVER_PORT = 5006
PROTOCOL_VERSION = 1
MAX_PROTOCOL_VERSION = 1
PROTOCOL_PREAMBLE = "pixelvloed"
MAX_PIXELS = 140

class Canvas(object):
  """PixelVloed display class"""

  def __init__(self, queue, options):
    """Init the pixelVloed server"""
    self.debug = options.debug if options.debug else False
    self.pixeloffset = 2
    self.fps = 30
    self.screen = None
    self.udp_ip = options.ip if options.ip else UDP_IP
    self.udp_port = options.port if options.port else UDP_PORT
    self.factor = options.factor if options.factor else 1
    self.canvas()
    self.set_title()
    self.queue = queue
    self.limit = options.maxpixels if options.maxpixels else MAX_PIXELS
    self.pixels = None
    self.broadcastsocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    self.broadcastsocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    self.broadcastsocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

  @staticmethod
  def set_title(text=None):
    """Sets the window title"""
    title = 'PixelVloed %0.02f' % __version__
    if text:
      title += ' ' + text
    pygame.display.set_caption(title)

  def canvas(self):
    """Init the pygame canvas"""
    pygame.init()
    screeninfo = pygame.display.Info()
    self.width = options.width if options.width else screeninfo.current_w
    self.height = options.height if options.height else screeninfo.current_h
    pygame.mixer.quit()
    self.screen = pygame.display.set_mode((self.width, self.height),
                                          pygamelocals.DOUBLEBUF)

  def clear(self, r=0, g=0, b=0): # pylint: disable=C0103
    """ Fill the entire screen with a solid colour (default: black)"""
    self.screen.fill((r, g, b))

  def Pixel(self, x, y, r, g, b, a=255): # pylint: disable=C0103
    """Print a pixel to the screen"""
    try:
      if a == 255:
        color = (r*256*256) + (g*256) + b
        if self.factor>1:
          for w in xrange(0, self.factor):
            for h in xrange(0, self.factor):
              self.pixels[(x*self.factor) + w][(y*self.factor) + h] = color
        else:
          self.pixels[x][y] = color
      else:
        old = self.pixels[x][y]
        oldr = old >> 16
        oldg = (old & 0x00ff00) / 256
        oldb = old & 0x0000ff
        red = (r * a) + (oldr * (1.0 - a))
        green = (g * a) + (oldg * (1.0 - a))
        blue = (b * a) + (oldb * (1.0 - a))
        self.pixels[x][y] = (red*256*256) + (green*256) + blue
    except IndexError:
      pass

  def CanvasUpdate(self):
    """Updates the screen according to self.fps"""
    lasttime = lastbroadcast = time.time()
    changed = False
    while True:
      changed = self.Draw() or changed
      if time.time() - lastbroadcast > 2:
        lastbroadcast = time.time()
        self.SendDiscoveryPacket()

      if time.time() - lasttime >= 1.0 / self.fps and changed:
        self.pixels = None # release the lock on these pixels so we can flip
        pygame.display.flip()
        changed = False
        lasttime = time.time()
      else:
        time.sleep(1.0 / self.fps)

  def Draw(self):
    """Draws pixels specified in the received packages in the queue"""
    if self.queue.empty():
      # indicate that nothing was done, and we can skip flipping the screen
      return False
    #access the pixel array and lock it
    self.pixels = pygame.surfarray.pixels2d(self.screen)
    returntime = time.time() + (1.0 / self.fps)
    # while we have stuff in the queue, and its not our next time to draw a
    # frame, lets process packets from the queue
    while time.time() < returntime and not self.queue.empty():
      try:
        data = self.queue.get()
        preamble = struct.unpack_from("<?", data)[0]
        protocol = struct.unpack_from("<B", data, 1)[0]
        packetformat = ("<2H4B" if preamble else "<2H3B")
        pixellength = (8 #xx,yy,r,g,b,a
                       if preamble else
                       7 #xx,yy,r,g,b
                       )
        pixelcount = min(((len(data)-1) / pixellength),
                         self.limit)
        if self.debug:
          print '%d pixels received, protocol V %d' % (pixelcount, protocol)
        for i in xrange(0, pixelcount):
          pixel = struct.unpack_from(
              packetformat,
              data,
              self.pixeloffset + (i*pixellength))
          if self.debug:
            print pixel
          self.Pixel(*pixel)
      except Exception as error:
        if self.debug:
          # All exceptions will be printed, but won't result in a crash.
          print error
    # indicate that we have been drawing stuff
    return True

  def SendDiscoveryPacket(self):
    """Lets send out our ip/port/resolution to any listening clients"""
    try:
      self.broadcastsocket.sendto(
          '%s:%f %s:%d %d*%d' % (
              PROTOCOL_PREAMBLE, PROTOCOL_VERSION,
              self.udp_ip, self.udp_port,
              self.width/self.factor, self.height/self.factor),
          ('<broadcast>', DISCOVER_PORT))
      if self.debug:
        print 'sending discovery packet'
    except Exception as error:
      if self.debug:
        print error

  def __del__(self):
    """Clean up any sockets we created"""
    self.broadcastsocket.close()

class PixelVloedClient(object):
  """Sets up a client

  Arguments:
    firstserver: (bool) False, select the first server immediately
    debug: (bool) False
    ip: (str) None
    port: (int) None
    width: (int) 640
    height: (int) 480

  Listens for servers if no ip is given
  """

  def __init__(self, firstserver=False, debug=False,
               ip=None, port=None,
               width=640, height=480):
    self.sleep = 0.01
    self.debug = debug
    if not ip:
      servers = False
      while servers == False:
        servers = self.DiscoverServers(firstserver)
      self.ipaddress = servers[0]['ip']
      self.port = servers[0]['port']
      self.width = servers[0]['width']
      self.height = servers[0]['height']

      if self.debug:
        print ('displaying on %(ip)s:%(port)d, %(width)d*%(height)dpx' %
            servers[0])
    else:
      self.ipaddress = ip
      self.port = port if port else UDP_PORT
      self.width = width
      self.height = height
      if self.debug:
        print ('displaying on %(ipaddress)s:%(port)d, %(width)d*%(height)dpx' %
            {'ipaddress': self.ipaddress,
             'port': self.port,
             'width': self.width,
             'height': self.height})
    self.sock = socket.socket(socket.AF_INET, # Internet
                              socket.SOCK_DGRAM) # UDP

  def Sleep(self, duration=None):
    """Sleeps the designated amount of time"""
    time.sleep(duration if duration else self.sleep)

  def SendPacket(self, message, sleep=0.01):
    """Sends the message to the udp server

    Arguments:
      message: (str, 140)
      sleep:  (float) 0.01, duration of time the client should sleep
    """
    self.sock.sendto(message, (self.ipaddress, self.port))
    if sleep:
      self.Sleep(duration=sleep)

  @staticmethod
  def DiscoverServers(returnfirst=False, timeout=5):
    """Discover servers that send out the pixelvloed preample"""
    discoverysock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    discoverysock.bind(('', DISCOVER_PORT))
    starttime = time.time()
    servers = []
    foundhash = {}
    while (time.time() - timeout) < starttime:
      data, _addr = discoverysock.recvfrom(1024)
      try:
        if data.startswith(PROTOCOL_PREAMBLE):
          dataset = data.split(' ')
          if float(dataset[0].split(':')[1]) <= MAX_PROTOCOL_VERSION:
            ipaddress = dataset[1].split(':')[0]
            port = int(dataset[1].split(':')[1])
            width = int(dataset[2].split('*')[0])
            height = int(dataset[2].split('*')[1])
            if data not in foundhash:
              newserver = {'ip': ipaddress,
                           'port': port,
                           'width': width,
                           'height': height}
              foundhash[data] = True
              print 'New pixelvloed screen found: %r' % newserver
              servers.append(newserver)
              if returnfirst:
                return servers
      except:
        pass
    if servers:
      return servers
    return False

def NewMessage():
  """Creates a new message with the correct max size, rgb mode and version"""
  message = MaxSizeList(MAX_PIXELS+2)
  message.append(SetRGBAMode(False))
  message.append(SetVersionBit())
  return message

def RGBPixel(x, y, r, g, b, a=None): # pylint: disable=C0103
  """Generates the packed data for a pixel"""
  if a is not None:
    return struct.pack("<2H4B", x, y, r, g, b, a)
  return struct.pack("<2H3B", x, y, r, g, b)

def SetRGBAMode(mode):
  """Generate the rgb/rgba bit"""
  return struct.pack("<?", mode)

def SetVersionBit(protocol=1):
  """Generate the Version bit"""
  return struct.pack("<B", protocol)

class MaxSizeList(list):
  """A list that raises an indexError when it reaches the designated max size"""
  def __init__(self, maxcount=100):
    """Inits a list with a maxcount

    Arguments:
      maxcount: (int) 100
    """
    self.maxsize = maxcount
    super(MaxSizeList, self).__init__()

  def append(self, item):
    """Appends an item to the list"""
    if self.__len__() == self.maxsize:
      raise IndexError('max size reached')
    super(MaxSizeList, self).append(item)

def RunServer(options):
  """Runs a pixelvloed server"""
  PixelVloedServer('%s:%d' %(options.ip, options.port),
                   options=options).serve_forever()

if __name__ == '__main__':
  import pygame
  from pygame import locals as pygamelocals

  from gevent.server import DatagramServer
  from gevent.queue import Queue

  class PixelVloedServer(DatagramServer):
    """PixelVloed server class"""

    def __init__(self, *args, **kwargs):
      """Set up some vars for this instance"""
      self.queue = Queue()
      pixelcanvas = Canvas(self.queue, kwargs['options'])
      __request_processing_greenlet = spawn(pixelcanvas.CanvasUpdate)
      del (kwargs['options'])
      DatagramServer.__init__(self, *args, **kwargs)

    def handle(self, data, _address):
      """Is called by the DataGramServer whenever an udp package is received"""
      self.queue.put(data)

  import optparse
  parser = optparse.OptionParser()
  parser.add_option('-v', action="store_true", dest="debug", default=False)
  parser.add_option('-i', action="store", dest="ip", default=UDP_IP)
  parser.add_option('-p', action="store", dest="port", default=UDP_PORT,
                    type="int")
  parser.add_option('-x', action="store", dest="width", type="int")
  parser.add_option('-y', action="store", dest="height", type="int")
  parser.add_option('-m', action="store", dest="maxpixels", default=MAX_PIXELS,
                    type="int")
  parser.add_option('-f', action="store", dest="factor", default=1,
                    type="int")
  options, remainder = parser.parse_args()
  try:
    RunServer(options)
  except KeyboardInterrupt:
    print 'Closing server'
