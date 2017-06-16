#!/usr/bin/python
"""This is a udp / binary version of PixelFlut

Inspired by the PixelFlut projector on eth0:winter 2016 and
code from https://github.com/defnull/pixelflut/

This version runs without PyGame but uses SDL instead
"""

__version__ = 0.4
__author__ = "Jan Klopper <jan@underdark.nl>"

# import gevent monkeypatching and perform patch_all before anything else to
# avoid nasty eception on python closing time
if __name__ == '__main__':
  from gevent import spawn, monkey
  monkey.patch_all()

try:
  import gtk
except ImportError:
  gtk = None

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
DEFAULT_WIDTH = 1366
DEFAULT_HEIGHT = 786

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
    return title

  def canvas(self):
    """Init the pygame canvas"""
    sdl2.ext.init()
    if gtk:
      window = gtk.Window()
      screen = window.get_screen()
    self.width = gtk.gdk.screen_width() if gtk else DEFAULT_WIDTH
    self.height = gtk.gdk.screen_height() if gtk else DEFAULT_HEIGHT
    self.width = options.width if options.width else self.width
    self.height = options.height if options.height else self.height
    self.screen = sdl2.ext.Window(self.set_title(),
                                  size=(self.width, self.height))
    self.screen.show()
    self.surface = self.screen.get_surface()

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
      #events = sdl2.ext.get_events()
      #for event in events:
      #  if event.type == sdl2.SDL_QUIT:
      #    sys.exit()
      #    break
      if time.time() - lastbroadcast > 2:
        lastbroadcast = time.time()
        self.SendDiscoveryPacket()

      if time.time() - lasttime >= 1.0 / self.fps and changed:
        self.pixels = None # release the lock on these pixels so we can flip
        self.screen.refresh()
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
    self.pixels = sdl2.ext.pixels2d(self.surface)
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

if __name__ == '__main__':
  import sdl2.ext

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
